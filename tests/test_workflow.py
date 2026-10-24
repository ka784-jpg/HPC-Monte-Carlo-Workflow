import copy
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mcflow.analysis import aggregate, inspect_run, wilson
from mcflow.engine import count_hits
from mcflow.manifest import initialize, load_manifest, make_manifest, task_path, validate_config
from mcflow.runner import run_local, run_task, task_lock
from mcflow.slurm import index_ranges, prepare_slurm
from mcflow.storage import WorkflowError, digest, read_record, write_record


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {"samples": [101, 1003], "replicates": 3, "master_seed": 41, "chunk_size": 100}
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.run = self.root / "run"
        initialize(self.config_path, self.run)

    def result(self, task=0, run=None):
        return read_record(task_path(run or self.run, "results", task))

    def test_manifest_reproducible_and_seeds_distinct(self):
        first = load_manifest(self.run)
        self.assertEqual(first, make_manifest(self.config))
        self.assertEqual(len({t["seed"] for t in first["tasks"]}), 6)

    def test_seed_is_independent_of_task_order_and_chunk_size(self):
        changed = {**self.config, "samples": [1003], "chunk_size": 7}
        a = make_manifest(self.config)["tasks"][3:]
        b = make_manifest(changed)["tasks"]
        self.assertEqual([t["seed"] for t in a], [t["seed"] for t in b])

    def test_seed_changes_with_master_seed(self):
        a = make_manifest(self.config)["tasks"][0]["seed"]
        b = make_manifest({**self.config, "master_seed": 42})["tasks"][0]["seed"]
        self.assertNotEqual(a, b)

    def test_invalid_configurations(self):
        bad = [{"samples": []}, {"samples": [2, 1]}, {"samples": [1, 1]},
               {"samples": [True]}, {"samples": [0]}, {"samples": [1.0]},
               {"replicates": 0}, {"replicates": True}, {"chunk_size": 0},
               {"master_seed": -1}, {"master_seed": 2**64}, {"extra": 1}]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(WorkflowError):
                validate_config({**self.config, **change})

    def test_config_missing_key_and_excessive_tasks(self):
        bad = dict(self.config)
        bad.pop("master_seed")
        with self.assertRaises(WorkflowError):
            validate_config(bad)
        with self.assertRaises(WorkflowError):
            validate_config({**self.config, "samples": list(range(1, 12)), "replicates": 10000})

    def test_init_never_overwrites(self):
        before = (self.run / "manifest.json").read_bytes()
        with self.assertRaises(WorkflowError):
            initialize(self.config_path, self.run)
        self.assertEqual(before, (self.run / "manifest.json").read_bytes())

    def test_manifest_tampering_even_with_recomputed_checksum(self):
        manifest = load_manifest(self.run)
        manifest["tasks"][0]["samples"] += 1
        write_record(self.run / "manifest.json", manifest)
        with self.assertRaises(WorkflowError):
            load_manifest(self.run)

    def test_kernel_known_points(self):
        class Points:
            def __init__(self):
                self.values = iter([0, 0, 1, 0, 0.9, 0.9, 0.5, 0.5])

            def random(self):
                return next(self.values)
        self.assertEqual(count_hits(Points(), 4), 3)

    def test_independent_reference_loop(self):
        task = load_manifest(self.run)["tasks"][3]
        rng = random.Random(int(task["seed"]))
        expected = sum(math.hypot(rng.random(), rng.random()) <= 1 for _ in range(task["samples"]))
        run_task(self.run, 3)
        self.assertEqual(self.result(3)["hits"], expected)

    def test_resume_matches_uninterrupted(self):
        other = self.root / "other"
        initialize(self.config_path, other)
        self.assertEqual(run_task(self.run, 3, max_chunks=2), "paused")
        saved = read_record(task_path(self.run, "checkpoints", 3))
        self.assertEqual(saved["completed"], 200)
        self.assertEqual(run_task(self.run, 3), "complete")
        run_task(other, 3)
        self.assertEqual(self.result(3), self.result(3, other))
        self.assertFalse(task_path(self.run, "checkpoints", 3).exists())

    def test_changed_chunk_size_preserves_results(self):
        changed = self.root / "changed.json"
        changed.write_text(json.dumps({**self.config, "chunk_size": 37}), encoding="utf-8")
        other = self.root / "other"
        initialize(changed, other)
        run_task(self.run, 3)
        run_task(other, 3)
        self.assertEqual(self.result(3)["hits"], self.result(3, other)["hits"])

    def test_finished_task_is_not_rewritten(self):
        run_task(self.run, 0)
        path = task_path(self.run, "results", 0)
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.assertEqual(run_task(self.run, 0), "skipped")
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))

    def test_lock_prevents_duplicate_worker(self):
        with task_lock(self.run, 0):
            with self.assertRaisesRegex(WorkflowError, "locked"):
                run_task(self.run, 0)
        self.assertEqual(run_task(self.run, 0), "complete")

    def test_lock_cleanup_on_worker_exception(self):
        with patch("mcflow.runner.count_hits", side_effect=RuntimeError("worker error")):
            with self.assertRaises(RuntimeError):
                run_task(self.run, 0)
        self.assertFalse((self.run / "locks" / "000000.lock").exists())

    def test_low_disk_refuses_work(self):
        usage = shutil.disk_usage(self.run)._replace(free=0)
        with patch("mcflow.runner.shutil.disk_usage", return_value=usage):
            with self.assertRaisesRegex(WorkflowError, "MiB"):
                run_task(self.run, 0)
        self.assertFalse(task_path(self.run, "results", 0).exists())

    def test_corrupt_checkpoint_is_not_overwritten(self):
        run_task(self.run, 3, max_chunks=1)
        path = task_path(self.run, "checkpoints", 3)
        path.write_text('{"broken": true}', encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaises(WorkflowError):
            run_task(self.run, 3)
        self.assertEqual(before, path.read_bytes())

    def test_invalid_rng_and_interpreter_are_rejected(self):
        run_task(self.run, 3, max_chunks=1)
        path = task_path(self.run, "checkpoints", 3)
        saved = read_record(path)
        bad = copy.deepcopy(saved)
        bad["rng_state"][1][-1] = 999
        write_record(path, bad)
        with self.assertRaises(WorkflowError):
            run_task(self.run, 3)
        bad = {**saved, "python": "0.0.0"}
        write_record(path, bad)
        with self.assertRaisesRegex(WorkflowError, "major.minor"):
            run_task(self.run, 3)

    def test_corrupt_result_blocks_resume_and_collection(self):
        run_local(self.run)
        path = task_path(self.run, "results", 0)
        text = json.loads(path.read_text())
        text["payload"]["hits"] += 1
        path.write_text(json.dumps(text), encoding="utf-8")
        with self.assertRaisesRegex(WorkflowError, "Checksum"):
            run_task(self.run, 0)
        with self.assertRaises(WorkflowError):
            aggregate(self.run)

    def test_foreign_result_rejected(self):
        run_task(self.run, 0)
        path = task_path(self.run, "results", 0)
        saved = self.result()
        saved["manifest_sha256"] = "foreign"
        write_record(path, saved)
        with self.assertRaisesRegex(WorkflowError, "identity"):
            run_task(self.run, 0)

    def test_invalid_counts_rejected(self):
        run_task(self.run, 0)
        path = task_path(self.run, "results", 0)
        original = self.result()
        for change in ({"hits": -1}, {"hits": 102}, {"hits": True}, {"completed": 100}):
            with self.subTest(change=change):
                write_record(path, {**original, **change})
                with self.assertRaises(WorkflowError):
                    run_task(self.run, 0)

    def test_missing_and_unexpected_results_block_aggregation(self):
        with self.assertRaises(WorkflowError):
            aggregate(self.run)
        self.assertFalse((self.run / "analysis" / "summary.json").exists())
        run_local(self.run)
        shutil.copyfile(task_path(self.run, "results", 0), self.run / "results" / "extra.json")
        with self.assertRaises(WorkflowError):
            aggregate(self.run)

    def test_aggregate_counts_and_replicates(self):
        run_local(self.run)
        result = aggregate(self.run)
        self.assertEqual(result["task_count"], 6)
        self.assertEqual(result["total_samples"], 3 * (101 + 1003))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["groups"][0]["replicates"], 3)
        self.assertEqual(result, aggregate(self.run))

    def test_status_accounts_for_all_task_states(self):
        run_task(self.run, 0)
        run_task(self.run, 3, max_chunks=1)
        with task_lock(self.run, 1):
            result, _ = inspect_run(self.run)
        self.assertEqual(result["counts"], {"complete": 1, "checkpointed": 1,
                                          "pending": 3, "locked": 1, "invalid": 0})

    def test_serial_equals_parallel(self):
        other = self.root / "parallel"
        initialize(self.config_path, other)
        run_local(self.run, workers=1)
        with patch.dict(os.environ, {"SLURM_CPUS_PER_TASK": "2"}):
            run_local(other, workers=2)
        for task in range(6):
            self.assertEqual(self.result(task), self.result(task, other))

    def test_worker_budget_enforced(self):
        with patch.dict(os.environ, {"SLURM_CPUS_PER_TASK": "1"}):
            with self.assertRaisesRegex(WorkflowError, "CPU limit"):
                run_local(self.run, workers=2)

    def test_stop_request_preserves_checkpoint(self):
        run_task(self.run, 3, max_chunks=1)
        before = task_path(self.run, "checkpoints", 3).read_bytes()
        self.assertEqual(run_task(self.run, 3, stop=lambda: True), "paused")
        self.assertEqual(before, task_path(self.run, "checkpoints", 3).read_bytes())

    def test_invalid_task_and_chunk_limit(self):
        for task_id in (-1, 6, True):
            with self.assertRaises(WorkflowError):
                run_task(self.run, task_id)
        with self.assertRaises(WorkflowError):
            run_task(self.run, 0, max_chunks=0)

    def test_atomic_replace_failure_preserves_old_record(self):
        path = self.root / "record.json"
        write_record(path, {"old": True})
        with patch("mcflow.storage.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                write_record(path, {"new": True})
        self.assertEqual(read_record(path), {"old": True})
        self.assertFalse(list(self.root.glob(".write-*")))

    def test_windows_transient_replace_is_retried(self):
        path = self.root / "record.json"
        error = PermissionError("temporary sharing violation")
        error.winerror = 32
        original = os.replace
        calls = []

        def replacement(source, destination):
            calls.append(1)
            if len(calls) == 1:
                raise error
            return original(source, destination)

        with patch("mcflow.storage.WINDOWS", True), patch("mcflow.storage.time.sleep"), \
                patch("mcflow.storage.os.replace", side_effect=replacement):
            write_record(path, {"value": 1})
        self.assertEqual(len(calls), 2)
        self.assertEqual(read_record(path), {"value": 1})

    def test_persistent_windows_permission_error_has_bounded_retries(self):
        path = self.root / "record.json"
        write_record(path, {"old": True})
        error = PermissionError("persistent access denial")
        error.winerror = 5
        with patch("mcflow.storage.WINDOWS", True), patch("mcflow.storage.time.sleep"), \
                patch("mcflow.storage.os.replace", side_effect=error) as replace:
            with self.assertRaises(PermissionError):
                write_record(path, {"new": True})
            self.assertEqual(replace.call_count, 7)
        self.assertEqual(read_record(path), {"old": True})

    def test_wilson_boundaries_and_known_case(self):
        self.assertAlmostEqual(wilson(0, 10)[1], 0.2775327998628892)
        self.assertAlmostEqual(wilson(10, 10)[0], 0.7224672001371107)
        self.assertAlmostEqual(wilson(5, 10)[0], 0.236593090512564)
        self.assertAlmostEqual(sum(wilson(5, 10)), 1.0)
        self.assertGreater(wilson(0, 10)[1], 0)
        for args in ((0, 0), (-1, 10), (11, 10), (1, 10, 1)):
            with self.assertRaises(WorkflowError):
                wilson(*args)

    def test_slurm_is_generation_only_and_retry_selects_missing(self):
        run_task(self.run, 0)
        command = prepare_slurm(self.run, pending=True, concurrency=2, python="/opt/my env/bin/python")
        self.assertIn("--array=1-5%2", command)
        script = (self.run / "submit.sbatch").read_text()
        self.assertIn("'/opt/my env/bin/python'", script)
        self.assertIn("SLURM_ARRAY_TASK_ID", script)
        self.assertIn(digest(load_manifest(self.run)), script)
        self.assertEqual(inspect_run(self.run)[0]["counts"]["complete"], 1)

    def test_slurm_rejects_locks_invalid_options_and_finished_retry(self):
        with task_lock(self.run, 0), self.assertRaises(WorkflowError):
            prepare_slurm(self.run)
        for kwargs in ({"walltime": "1;echo bad"}, {"concurrency": 0}, {"python": "python\n"}):
            with self.assertRaises(WorkflowError):
                prepare_slurm(self.run, **kwargs)
        run_local(self.run)
        with self.assertRaisesRegex(WorkflowError, "No unfinished"):
            prepare_slurm(self.run, pending=True)

    def test_index_ranges(self):
        self.assertEqual(index_ranges([1, 2, 3, 5, 7, 8]), "1-3,5,7-8")
        self.assertEqual(index_ranges([]), "")
        self.assertEqual(index_ranges([0]), "0")

    def test_cli_pause_exit_code_and_manifest_guard(self):
        result = subprocess.run([sys.executable, "-m", "mcflow", "task", str(self.run),
                                 "--task-id", "3", "--max-chunks", "1"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 75, result.stderr)
        result = subprocess.run([sys.executable, "-m", "mcflow", "task", str(self.run),
                                 "--task-id", "3", "--expect-manifest", "bad"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("manifest differs", result.stderr)

    @unittest.skipIf(os.name == "nt", "POSIX signal delivery test")
    def test_sigterm_checkpoint_and_resume(self):
        config = {**self.config, "samples": [3000000], "replicates": 1, "chunk_size": 10000}
        source = self.root / "signal.json"
        source.write_text(json.dumps(config), encoding="utf-8")
        target = self.root / "signal"
        initialize(source, target)
        process = subprocess.Popen([sys.executable, "-m", "mcflow", "task", str(target),
                                    "--task-id", "0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        import time
        try:
            deadline = time.monotonic() + 15
            while not task_path(target, "checkpoints", 0).exists() and process.poll() is None:
                if time.monotonic() > deadline:
                    self.fail("Checkpoint not created before timeout")
                time.sleep(0.005)
            process.terminate()
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 75, (stdout, stderr))
            self.assertFalse((target / "locks" / "000000.lock").exists())
            run_task(target, 0)
            task = load_manifest(target)["tasks"][0]
            expected = count_hits(random.Random(int(task["seed"])), task["samples"])
            self.assertEqual(read_record(task_path(target, "results", 0))["hits"], expected)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


if __name__ == "__main__":
    unittest.main()
