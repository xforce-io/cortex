import concurrent.futures
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
import unittest

from cortex import api
from cortex.app import CortexApp

ROOT = Path(__file__).resolve().parents[1]


class TestAPIErrorHandling(unittest.TestCase):
    """Test that API errors don't expose sensitive details to clients."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.app = CortexApp.open(self.home)

    def tearDown(self):
        self.app.conn.close()
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
        class BrokenApp:
            conn = None

            def healthz(self):
                raise RuntimeError("secret path /tmp/cortex.db line 42")

        original_factory = api.Handler.app_factory
        api.Handler.app_factory = staticmethod(lambda: BrokenApp())
        server = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/healthz"
        try:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self._api_get(url)

            response = cm.exception
            self.assertEqual(response.code, 500)
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload, {"error": "INTERNAL_SERVER_ERROR"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            api.Handler.app_factory = original_factory

    def test_api_handles_concurrent_dataset_writes(self):
        """Test that concurrent requests do not share a SQLite connection."""
        port = self._free_port()
        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["CORTEX_HOST"] = "127.0.0.1"
        env["CORTEX_PORT"] = str(port)
        env["PYTHONPATH"] = str(ROOT)
        server = subprocess.Popen(
            [sys.executable, "-m", "cortex.api"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_health(f"http://127.0.0.1:{port}/healthz")

            def create_dataset(index: int) -> tuple[int, str]:
                return self._api_post_status(
                    f"http://127.0.0.1:{port}/api/v1/datasets",
                    {"name": f"concurrent-{index}", "type": "tabular", "owner": "alice", "team": "ml"},
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
                results = list(executor.map(create_dataset, range(40)))

            failures = [(status, body) for status, body in results if status != 201]
            self.assertEqual(failures, [])
        finally:
            server.send_signal(signal.SIGINT)
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
        with opener.open(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))

    def _api_post_status(self, url: str, payload: dict) -> tuple[int, str]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=8) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


if __name__ == "__main__":
    unittest.main()
