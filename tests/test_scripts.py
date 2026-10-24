import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from mcflow.manifest import initialize, load_manifest, task_path
from mcflow.runner import run_local, run_task
from mcflow.storage import digest, read_record

ROOT = Path(__file__).resolve().parents[1]
HAS_BASH = os.name != "nt" and shutil.which("bash") is not None
HAS_PLOTS = importlib.util.find_spec("matplotlib") is not None

FAKE_DRIVER = '''import json, os, pathlib, sys
command, *args = sys.argv[1:]
log = pathlib.Path(os.environ["FAKE_SLURM_LOG"])
with log.open("a") as stream:
    stream.write(json.dumps([command, *args]) + "\\n")
if command == "sbatch":
    collector = any(arg.endswith("collect.sbatch") for arg in args)
    if collector and os.environ.get("FAKE_COLLECTOR_FAIL"):
        sys.exit(1)
    print("91001" if collector else "91000")
elif command == "squeue":
    print(os.environ.get("FAKE_QUEUE", ""))
elif command == "sacct":
    print(os.environ.get("FAKE_ACCOUNTING", ""))
'''


@unittest.skipUnless(HAS_BASH, "Bash/Slurm wrappers are tested on Linux")
class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mcflow scripts ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "run with spaces"
        config = self.root / "config.json"
        config.write_text(json.dumps({"samples": [101, 503], "replicates": 2,
                                      "master_seed": 17, "chunk_size": 100}))
        initialize(config, self.run)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        driver = self.root / "fake_slurm.py"
        driver.write_text(FAKE_DRIVER)
        self.log = self.root / "scheduler.jsonl"
        for name in ("sbatch", "squeue", "sacct"):
            script = self.bin / name
            script.write_text('#!/usr/bin/env bash\nexec "$PYTHON" "$FAKE_SLURM_DRIVER" "$(basename "$0")" "$@"\n')
            script.chmod(0o755)
        self.env = {**os.environ, "PYTHON": sys.executable, "FAKE_SLURM_DRIVER": str(driver),
                    "FAKE_SLURM_LOG": str(self.log), "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "PYTHONPATH": str(ROOT / "src"), "MC_MIN_FREE_MB": "0"}

    def shell(self, script, *args, **environment):
        return subprocess.run(["bash", str(ROOT / script), *map(str, args)],
                              env={**self.env, **environment}, capture_output=True, text=True, timeout=30)

    def helper(self, *args, stdin=None):
        return subprocess.run([sys.executable, str(ROOT / "scripts/run_info.py"), *map(str, args)],
                              env=self.env, input=stdin, capture_output=True, text=True, timeout=15)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def complete_accounting(self, ids=range(4)):
        return "\n".join(f"91000_{index}|COMPLETED|0:0" for index in ids)

    def test_all_shell_files_have_valid_bash_syntax(self):
        for path in [*ROOT.glob("scripts/*.sh"), *ROOT.glob("slurm/*.sbatch")]:
            with self.subTest(path=path.name):
                result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_preflight_and_submit_dry_run_never_contact_scheduler(self):
        result = self.shell("scripts/preflight.sh", self.run, "--slurm")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.shell("scripts/submit.sh", self.run)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--array=0-3%4", result.stdout)
        self.assertIn("monte_carlo.sbatch", result.stdout)
        self.assertIn("Dry run", result.stdout)
        self.assertEqual(self.calls(), [])

    def test_explicit_submission_and_receipt(self):
        result = self.shell("scripts/submit.sh", self.run, "--submit", MC_ACCOUNT="project demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertIn("--account=project demo", calls[0])
        self.assertIn(str(self.run), calls[0])
        receipt = read_record(self.run / "submissions/job-91000.json")
        self.assertEqual(receipt["task_ids"], [0, 1, 2, 3])
        self.assertEqual(receipt["array_job_id"], "91000")
        self.assertFalse((self.run / ".submission.lock").exists())

    @unittest.skipUnless(HAS_PLOTS, "Collector requires plotting support")
    def test_collector_has_afterok_dependency(self):
        result = self.shell("scripts/submit.sh", self.run, "--collect", "--submit")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertIn("--dependency=afterok:91000", calls[1])
        self.assertIn(str(ROOT / "slurm/collect.sbatch"), calls[1])
        receipt = read_record(self.run / "submissions/job-91000.json")
        self.assertEqual(receipt["collector_job_id"], "91001")

    @unittest.skipUnless(HAS_PLOTS, "Collector requires plotting support")
    def test_failed_collector_keeps_array_receipt(self):
        result = self.shell("scripts/submit.sh", self.run, "--collect", "--submit", FAKE_COLLECTOR_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NOT been cancelled", result.stderr)
        receipt = read_record(self.run / "submissions/job-91000.json")
        self.assertEqual(receipt["array_job_id"], "91000")
        self.assertIsNone(receipt["collector_job_id"])
        self.assertEqual(len(self.calls()), 2)

    def test_retry_selects_unfinished_tasks_without_seed_changes(self):
        before = (self.run / "manifest.json").read_bytes()
        run_task(self.run, 0)
        result = self.shell("scripts/retry.sh", self.run)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--array=1-3%4", result.stdout)
        self.assertEqual(before, (self.run / "manifest.json").read_bytes())
        self.assertEqual(self.calls(), [])

    def test_submission_lock_blocks_sbatch(self):
        (self.run / ".submission.lock").mkdir()
        result = self.shell("scripts/submit.sh", self.run, "--submit")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Submission lock", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_batch_worker_runs_real_task_and_rejects_wrong_manifest(self):
        identity = digest(load_manifest(self.run))
        result = self.shell("slurm/monte_carlo.sbatch", self.run, sys.executable, identity, SLURM_ARRAY_TASK_ID="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(task_path(self.run, "results", 0).exists())
        result = self.shell("slurm/monte_carlo.sbatch", self.run, sys.executable, "wrong", SLURM_ARRAY_TASK_ID="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(task_path(self.run, "results", 1).exists())

    @unittest.skipUnless(HAS_PLOTS, "Rendering requires plotting support")
    def test_local_and_collector_wrappers(self):
        result = self.shell("scripts/run_local.sh", self.run, "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.run / "analysis/convergence.png").exists())
        result = self.shell("slurm/collect.sbatch", self.run, sys.executable, digest(load_manifest(self.run)))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.shell("slurm/collect.sbatch", self.run, sys.executable, "wrong")
        self.assertNotEqual(result.returncode, 0)

    def test_sleeper_file_mode_completes_without_scheduler(self):
        run_local(self.run)
        result = self.shell("scripts/sleeper.sh", self.run, "--interval", "1", "--timeout", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("complete and validated", result.stdout)
        self.assertEqual(self.calls(), [])

    def test_sleeper_times_out_instead_of_claiming_success(self):
        result = self.shell("scripts/sleeper.sh", self.run, "--interval", "1", "--timeout", "1")
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertIn("timed out", result.stderr)

    def test_sleeper_checks_all_array_elements(self):
        run_local(self.run)
        result = self.shell("scripts/sleeper.sh", self.run, "--job-id", "91000", "--timeout", "2",
                            FAKE_ACCOUNTING=self.complete_accounting())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({call[0] for call in self.calls()}, {"squeue", "sacct"})

    def test_sleeper_reports_scheduler_failure_even_with_valid_outputs(self):
        run_local(self.run)
        failed = self.complete_accounting().replace("91000_2|COMPLETED|0:0", "91000_2|FAILED|1:0")
        result = self.shell("scripts/sleeper.sh", self.run, "--job-id", "91000", FAKE_ACCOUNTING=failed)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Scheduler failure", result.stderr)

    def test_missing_accounting_waits_instead_of_succeeding(self):
        run_local(self.run)
        result = self.shell("scripts/sleeper.sh", self.run, "--job-id", "91000", "--interval", "1", "--timeout", "1",
                            FAKE_ACCOUNTING=self.complete_accounting([0, 1]))
        self.assertEqual(result.returncode, 124, result.stderr)

    def test_retry_receipt_scopes_accounting_to_actual_array(self):
        result = self.helper("receipt", self.run, "--job-id", "91000", "--indices", "2-3")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.helper("accounting", self.run, "--job-id", "91000", stdin=self.complete_accounting([2, 3]))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_options_and_foreign_accounting_fail(self):
        result = self.shell("scripts/submit.sh", self.run, MC_CONCURRENCY="0")
        self.assertNotEqual(result.returncode, 0)
        result = self.shell("scripts/sleeper.sh", self.run, "--interval", "0")
        self.assertNotEqual(result.returncode, 0)
        result = self.helper("accounting", self.run, "--job-id", "91000", stdin="other|COMPLETED|0:0")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
