import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
import unittest

from cortex.app import CortexApp

ROOT = Path(__file__).resolve().parents[1]


class TestAPIErrorHandling(unittest.TestCase):
    """Test that API errors don't expose sensitive details to clients."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.app = CortexApp.open(self.home)

    def tearDown(self):
        self.tmp.cleanup()

    def test_api_404_returns_generic_error(self):
        """Test that 404 endpoints return generic error structure."""
        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["CORTEX_HOST"] = "127.0.0.1"
        env["CORTEX_PORT"] = "8801"
        env["PYTHONPATH"] = str(ROOT)
        server = subprocess.Popen(
            [sys.executable, "-m", "cortex.api"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_health("http://127.0.0.1:8801/healthz")

            # Request a non-existent endpoint
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self._api_get("http://127.0.0.1:8801/api/v1/nonexistent")

            response = cm.exception
            self.assertEqual(response.code, 404)

            # Read the error response
            body = response.read().decode("utf-8")
            payload = json.loads(body)

            # Should have error field but not expose sensitive details
            self.assertIn("error", payload)
            self.assertEqual(payload["error"], "NOT_FOUND")

            # Should NOT have fields like 'traceback', 'exception', 'details'
            self.assertNotIn("traceback", payload)
            self.assertNotIn("exception", payload)

        finally:
            server.send_signal(subprocess.signal.SIGINT)
            server.wait(timeout=5)

    def test_api_500_returns_generic_error(self):
        """Test that server errors return generic messages without details."""
        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["CORTEX_HOST"] = "127.0.0.1"
        env["CORTEX_PORT"] = "8802"
        env["PYTHONPATH"] = str(ROOT)
        server = subprocess.Popen(
            [sys.executable, "-m", "cortex.api"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_health("http://127.0.0.1:8802/healthz")

            # Create a dataset first
            dataset = self._api_post(
                "http://127.0.0.1:8802/api/v1/datasets",
                {"name": "error-test", "type": "tabular", "owner": "alice", "team": "ml"},
            )

            # Try to get a non-existent dataset version (triggers ValueError)
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self._api_get(f"http://127.0.0.1:8802/api/v1/datasets/{dataset['id']}/versions/nonexistent")

            response = cm.exception
            self.assertEqual(response.code, 400)

            # Read the error response
            body = response.read().decode("utf-8")
            payload = json.loads(body)

            # Should have error field but not expose sensitive details
            self.assertIn("error", payload)

            # Should NOT have fields like 'traceback', 'exception', 'details'
            self.assertNotIn("traceback", payload)
            self.assertNotIn("exception", payload)
            # Should not expose file paths or line numbers
            self.assertNotIn("File", payload.get("error", ""))
            self.assertNotIn("line", payload.get("error", ""))

        finally:
            server.send_signal(subprocess.signal.SIGINT)
            server.wait(timeout=5)

    def test_api_422_returns_missing_field_error(self):
        """Test that validation errors return error codes without exposing details."""
        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["CORTEX_HOST"] = "127.0.0.1"
        env["CORTEX_PORT"] = "8803"
        env["PYTHONPATH"] = str(ROOT)
        server = subprocess.Popen(
            [sys.executable, "-m", "cortex.api"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_health("http://127.0.0.1:8803/healthz")

            # Try to create a project without required fields
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self._api_post("http://127.0.0.1:8803/api/v1/projects", {})

            response = cm.exception
            self.assertEqual(response.code, 422)

            body = response.read().decode("utf-8")
            payload = json.loads(body)

            self.assertIn("error", payload)
            self.assertIn("MISSING_FIELD", payload["error"])

        finally:
            server.send_signal(subprocess.signal.SIGINT)
            server.wait(timeout=5)

    def _wait_for_health(self, url: str) -> None:
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                if self._api_get(url)["status"] == "ok":
                    return
            except Exception:
                time.sleep(0.1)
        self.fail(f"API did not become healthy: {url}")

    def _api_get(self, url: str):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def _api_post(self, url: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise


if __name__ == "__main__":
    unittest.main()
