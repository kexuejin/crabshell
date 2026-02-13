import unittest
from pathlib import Path


class BuildWorkflowChecksTests(unittest.TestCase):
    def test_core_build_runs_fast_checks_before_heavy_verify(self):
        workflow = Path(".github/workflows/build.yml").read_text(encoding="utf-8")
        self.assertIn("Run fast CLI tests", workflow)
        self.assertIn("Build and Verify", workflow)
        self.assertLess(workflow.index("Run fast CLI tests"), workflow.index("Build and Verify"))


if __name__ == "__main__":
    unittest.main()
