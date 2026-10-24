import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from mcflow.manifest import initialize
from mcflow.plotting import plot
from mcflow.runner import run_local
from mcflow.storage import WorkflowError


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Install .[plots] to test rendering")
class PlottingTests(unittest.TestCase):
    def test_plot_files_are_generated_after_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            config.write_text(json.dumps({"samples": [100, 1000], "replicates": 3,
                                          "master_seed": 9, "chunk_size": 500}), encoding="utf-8")
            run = root / "run"
            initialize(config, run)
            with self.assertRaises(WorkflowError):
                plot(run)
            run_local(run)
            path = plot(run)
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertGreater(path.stat().st_size, 10000)
            self.assertTrue((run / "analysis" / "convergence.pdf").read_bytes().startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
