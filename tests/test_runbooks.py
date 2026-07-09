import unittest

from cortex.runbooks import get_runbook, list_runbooks


class RunbookCatalogTest(unittest.TestCase):
    def test_lists_repo_runbooks_with_sections(self):
        runbooks = list_runbooks()

        guangyuan = next((item for item in runbooks if item["id"] == "14-guangyuan-reproduction"), None)
        self.assertIsNotNone(guangyuan)
        self.assertEqual(guangyuan["title"], "Guangyuan Reproduction Runbook")
        self.assertEqual(guangyuan["path"], "docs/runbooks/14-guangyuan-reproduction.md")
        self.assertIn("Smoke reproduction", guangyuan["sections"])
        self.assertIn("Full preflight", guangyuan["sections"])
        self.assertIn("Runtime target and resource guard", guangyuan["sections"])
        self.assertIn("Cortex-side operating entrypoint", guangyuan["summary"])

    def test_get_runbook_returns_content_and_rejects_unknown_id(self):
        runbook = get_runbook("14-guangyuan-reproduction")

        self.assertIn("GUANGYUAN_RUNTIME_TARGET_REQUIRED", runbook["content"])
        self.assertIn("predictions/pred_result.npz", runbook["content"])

        with self.assertRaisesRegex(ValueError, "RUNBOOK_NOT_FOUND"):
            get_runbook("missing-runbook")


if __name__ == "__main__":
    unittest.main()
