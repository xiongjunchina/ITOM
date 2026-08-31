import json
import runpy
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
validate_release = runpy.run_path(str(REPO_ROOT / "scripts" / "validate-release.py"))["validate_release"]


class ReleaseManifestContractTest(unittest.TestCase):
    def test_committed_release_contract(self):
        self.assertEqual(validate_release(REPO_ROOT), "1.2.0-rc.1")

    def test_path_traversal_pointer_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "release").mkdir()
            (root / "release" / "current.json").write_text(
                json.dumps({"schema_version": 1, "current": "../outside.json"}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "safe JSON filename"):
                validate_release(root)


if __name__ == "__main__":
    unittest.main()
