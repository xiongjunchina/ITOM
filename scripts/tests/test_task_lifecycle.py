import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "task-lifecycle.py"


class TaskLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.env = {**os.environ, "ITOM_REPO_ROOT": str(self.root)}

    def tearDown(self): self.temp.cleanup()

    def run_cli(self, *args, ok=True):
        result = subprocess.run(["python3", str(SCRIPT), *args], env=self.env, text=True, capture_output=True)
        if ok and result.returncode: self.fail(result.stderr or result.stdout)
        return result

    def start(self): self.run_cli("start", "--id", "FIX-1", "--grade", "S", "--scope", "frontend", "--acceptance", "target|expected")
    def state(self): return json.loads((self.root / ".itom-task/current.json").read_text())

    def test_commit_requires_target_and_docs_assessment(self):
        self.start(); self.assertNotEqual(self.run_cli("gate", ok=False).returncode, 0)
        self.run_cli("target-verified", "--evidence", "focused test passed")
        self.assertNotEqual(self.run_cli("gate", ok=False).returncode, 0)
        self.run_cli("docs-assessed", "--assessment", "README and mirrors updated"); self.run_cli("gate")

    def test_second_failure_requires_root_cause(self):
        self.start(); self.run_cli("fail", "--target", "scrollbar", "--reason", "first")
        self.run_cli("fail", "--target", "scrollbar", "--reason", "second")
        self.assertTrue(self.state()["root_cause_required"])
        self.assertNotEqual(self.run_cli("target-verified", "--evidence", "claimed", ok=False).returncode, 0)
        self.run_cli("root-cause", "--summary", "container ownership was wrong")
        self.run_cli("target-verified", "--evidence", "browser target passed")

    def test_candidate_allows_only_one_ci_and_idc_attempt(self):
        self.start(); self.run_cli("target-verified", "--evidence", "passed")
        self.run_cli("docs-assessed", "--assessment", "no contract change"); self.run_cli("freeze")
        self.run_cli("ci-start", "--reference", "run-1"); self.run_cli("ci-finish", "--result", "passed")
        self.assertNotEqual(self.run_cli("ci-start", "--reference", "run-2", ok=False).returncode, 0)
        self.run_cli("idc-start", "--tag", "sha-1"); self.run_cli("idc-finish", "--result", "passed")
        self.assertNotEqual(self.run_cli("idc-start", "--tag", "sha-1", ok=False).returncode, 0)


if __name__ == "__main__": unittest.main()
