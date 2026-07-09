import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cortex.resource_guard import (
    ResourceGuardError,
    cleanup_resource_guard,
    parse_resource_guard,
    run_resource_guard,
)


class ResourceGuardTest(unittest.TestCase):
    def test_parse_resource_guard_prefers_nested_params(self):
        guard = parse_resource_guard({"min_free_gb": 1, "resource_guard": {"min_free_gb": 2, "temp_dir": "scratch"}})

        self.assertEqual(guard["minFreeGb"], 2.0)
        self.assertEqual(guard["tempDirName"], "scratch")

    def test_rejects_temp_dir_escape(self):
        with self.assertRaisesRegex(ValueError, "RESOURCE_GUARD_TEMP_DIR_INVALID"):
            parse_resource_guard({"resource_guard": {"temp_dir": "../outside"}})

    def test_local_disk_guard_fails_when_space_is_low(self):
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            usage = mock.Mock()
            usage.free = 1024

            with mock.patch("shutil.disk_usage", return_value=usage):
                with self.assertRaisesRegex(ResourceGuardError, "RESOURCE_GUARD_FAILED:disk"):
                    run_resource_guard(
                        {"params": {"resource_guard": {"min_free_gb": 1, "temp_dir": "scratch"}}, "runtimeTarget": {"id": "local", "kind": "local"}},
                        work_dir,
                    )

    def test_remote_resource_guard_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_resource_guard(
                {
                    "params": {"resource_guard": {"min_free_gb": 1, "temp_dir": "scratch"}},
                    "runtimeTarget": {"id": "remote-gpu", "kind": "ssh", "capabilities": ["gpu"]},
                },
                Path(tmp),
            )

            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["checks"][0]["reason"], "remote_not_checked")

    def test_cleanup_only_removes_guard_owned_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            temp_dir = work_dir / "scratch"
            temp_dir.mkdir()
            (temp_dir / "data.tmp").write_text("tmp", encoding="utf-8")
            log = work_dir / "stdout.log"
            log.write_text("keep", encoding="utf-8")
            guard = {"createdTempDir": True, "tempDir": str(temp_dir), "cleanupOnFailure": True}

            cleanup_resource_guard(guard, work_dir)

            self.assertFalse(temp_dir.exists())
            self.assertTrue(log.exists())


if __name__ == "__main__":
    unittest.main()
