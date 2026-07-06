from __future__ import annotations

import json
import mimetypes
import os
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .app import CortexApp


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"


class Handler(BaseHTTPRequestHandler):
    app = None

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _static(self, path: str) -> bool:
        if path == "/":
            target = WEB_ROOT / "index.html"
        elif path in {"/app.js", "/styles.css"}:
            target = WEB_ROOT / path.removeprefix("/")
        elif path.startswith("/web/"):
            target = WEB_ROOT / path.removeprefix("/web/")
        else:
            return False
        try:
            resolved = target.resolve()
            web_root = WEB_ROOT.resolve()
            if resolved != web_root / "index.html" and web_root not in resolved.parents:
                return False
            if not resolved.is_file():
                return False
            body = resolved.read_bytes()
            content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        except OSError:
            return False

    def do_GET(self) -> None:
        try:
            path = unquote(urlparse(self.path).path)
            query = parse_qs(urlparse(self.path).query)
            if self._static(path):
                return
            parts = [p for p in path.split("/") if p]
            if path == "/healthz":
                self._json(200, self.app.healthz())
            elif parts == ["api", "v1", "dashboard"]:
                self._json(200, self.app.dashboard())
            elif parts == ["api", "v1", "projects"]:
                self._json(200, self.app.list_projects())
            elif parts[:3] == ["api", "v1", "projects"] and len(parts) == 4:
                self._json(200, self.app.get_project(parts[3]))
            elif parts[:3] == ["api", "v1", "projects"] and len(parts) == 5 and parts[4] == "dashboard":
                self._json(200, self.app.dashboard(project_id=parts[3]))
            elif parts[:3] == ["api", "v1", "projects"] and len(parts) == 5 and parts[4] == "datasets":
                self._json(200, self.app.list_project_datasets(parts[3]))
            elif parts[:3] == ["api", "v1", "projects"] and len(parts) == 6 and parts[4:6] == ["training", "jobs"]:
                self._json(200, self.app.list_training_jobs(project_id=parts[3]))
            elif parts[:3] == ["api", "v1", "projects"] and len(parts) == 5 and parts[4] == "runs":
                self._json(200, self.app.list_runs(project_id=parts[3]))
            elif parts == ["api", "v1", "datasets"]:
                self._json(
                    200,
                    self.app.list_datasets(
                        tag=query.get("tag", [None])[0],
                        domain=query.get("domain", [None])[0],
                        dataset_type=query.get("type", [None])[0],
                        status=query.get("status", [None])[0],
                    ),
                )
            elif parts == ["api", "v1", "training", "templates"]:
                self._json(200, self.app.list_templates())
            elif parts == ["api", "v1", "training", "jobs"]:
                self._json(200, self.app.list_training_jobs())
            elif parts == ["api", "v1", "runs"]:
                self._json(200, self.app.list_runs())
            elif parts == ["api", "v1", "models"]:
                self._json(200, self.app.list_models())
            elif parts == ["api", "v1", "evaluations"]:
                self._json(200, self.app.list_evaluations())
            elif parts == ["api", "v1", "experiment-results"]:
                self._json(200, self.app.list_experiment_results())
            elif parts[:3] == ["api", "v1", "evaluations"] and len(parts) == 4:
                self._json(200, self.app.get_evaluation(parts[3]))
            elif parts[:3] == ["api", "v1", "experiment-results"] and len(parts) == 4:
                self._json(200, self.app.get_experiment_result(parts[3]))
            elif parts[:3] == ["api", "v1", "datasets"] and len(parts) == 4:
                self._json(200, self.app.get_dataset(parts[3]))
            elif parts[:3] == ["api", "v1", "training"] and len(parts) == 5 and parts[3] == "jobs":
                self._json(200, self.app.get_training_job(parts[4]))
            elif parts[:3] == ["api", "v1", "training"] and len(parts) == 6 and parts[3] == "jobs" and parts[5] == "logs":
                self._json(200, {"logs": self.app.get_job_logs(parts[4])})
            elif parts[:3] == ["api", "v1", "runs"] and len(parts) == 4:
                self._json(200, self.app.get_run(parts[3]))
            elif parts[:3] == ["api", "v1", "runs"] and len(parts) == 5 and parts[4] == "artifacts":
                self._json(200, self.app.list_run_artifacts(parts[3]))
            elif parts[:3] == ["api", "v1", "datasets"] and len(parts) == 7 and parts[4] == "versions" and parts[6] == "runs":
                self._json(200, self.app.dataset_lineage(f"{parts[3]}@{parts[5]}"))
            elif parts[:3] == ["api", "v1", "datasets"] and len(parts) == 5 and parts[4] == "versions":
                self._json(200, self.app.list_dataset_versions(parts[3]))
            elif parts[:3] == ["api", "v1", "datasets"] and len(parts) == 6 and parts[4] == "versions":
                self._json(200, self.app.get_dataset_version(parts[3], parts[5]))
            elif parts[:3] == ["api", "v1", "models"] and len(parts) == 5 and parts[4] == "aliases":
                self._json(200, self.app.list_model_aliases(parts[3]))
            else:
                self._json(404, {"error": "NOT_FOUND"})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            self._json(500, {"error": str(exc) or exc.__class__.__name__})

    def do_POST(self) -> None:
        try:
            path = unquote(urlparse(self.path).path)
            parts = [p for p in path.split("/") if p]
            body = self._body()
            if parts == ["api", "v1", "projects"]:
                self._json(
                    201,
                    self.app.create_project(
                        body["name"],
                        body.get("owner", "unknown"),
                        body.get("team", "unknown"),
                        body.get("description", ""),
                        body.get("status", "active"),
                    ),
                )
            elif parts[:3] == ["api", "v1", "projects"] and len(parts) == 5 and parts[4] == "datasets:link":
                self._json(
                    201,
                    self.app.link_project_dataset(
                        parts[3],
                        body["datasetId"],
                        body.get("role", "train"),
                        body.get("versionPolicy", "latest"),
                        body.get("pinnedVersion"),
                        body.get("addedBy", body.get("owner", "unknown")),
                        body.get("notes", ""),
                    ),
                )
            elif parts == ["api", "v1", "datasets"]:
                self._json(
                    201,
                    self.app.create_dataset(
                        body["name"],
                        body["type"],
                        body.get("owner", "unknown"),
                        body.get("team", "unknown"),
                        body.get("description", ""),
                        body.get("tags", []),
                        body.get("visibility", "team"),
                        body.get("projectId"),
                        body.get("domain", ""),
                        body.get("sourceSystem", ""),
                    ),
                )
            elif parts == ["api", "v1", "demo", "kmeans"]:
                self._json(201, self.app.create_kmeans_demo(body.get("projectId")))
            elif parts == ["api", "v1", "demo", "full-test"]:
                self._json(201, self.app.create_full_test_demo(body.get("projectId")))
            elif parts == ["api", "v1", "demo", "slow-training"]:
                self._json(201, self.app.create_slow_training_demo(body.get("projectId")))
            elif parts == ["api", "v1", "evaluations"]:
                self._json(
                    201,
                    self.app.evaluate_model_version(
                        body["registeredModelName"],
                        str(body["modelVersion"]),
                        body["testDatasetRef"],
                        body.get("owner", "unknown"),
                        body.get("team", "unknown"),
                    ),
                )
            elif parts[:3] == ["api", "v1", "datasets"] and len(parts) == 5 and parts[4] == "versions:import":
                self._json(
                    201,
                    self.app.import_dataset_version(
                        parts[3],
                        body.get("version", "v1"),
                        body["source"],
                        body.get("format", "csv"),
                        body.get("createdBy", body.get("owner", "unknown")),
                    ),
                )
            elif parts == ["api", "v1", "experiment-results:import-predictions"]:
                self._json(
                    201,
                    self.app.import_prediction_result(
                        body["experimentName"],
                        body["methodId"],
                        body.get("methodKind", ""),
                        body["source"],
                        body.get("createdBy", body.get("owner", "unknown")),
                        body.get("datasetRef", ""),
                    ),
                )
            elif parts[:3] == ["api", "v1", "datasets"] and len(parts) == 5 and parts[4] == "versions":
                self._json(
                    201,
                    self.app.add_dataset_version(
                        parts[3],
                        body.get("version", "v1"),
                        body["storageUri"],
                        body["format"],
                        checksum=body.get("checksum"),
                        schema=body.get("schema", {}),
                        split=body.get("split", {}),
                        created_by=body.get("createdBy", body.get("owner", "unknown")),
                    ),
                )
            elif parts == ["api", "v1", "training", "jobs"]:
                self._json(
                    201,
                    self.app.start_training_job(
                        body["templateId"],
                        body["datasetRef"],
                        body["experimentName"],
                        body.get("params", {}),
                        body.get("owner", "unknown"),
                        body.get("team", "unknown"),
                        body.get("projectId"),
                    ),
                )
            elif parts[:3] == ["api", "v1", "training"] and len(parts) == 6 and parts[3] == "jobs" and parts[5] == "cancel":
                self._json(200, self.app.cancel_training_job(parts[4], body.get("operator", "unknown")))
            elif parts[:3] == ["api", "v1", "training"] and len(parts) == 6 and parts[3] == "jobs" and parts[5] == "retry":
                self._json(201, self.app.retry_training_job(parts[4], wait=True))
            elif parts[:3] == ["api", "v1", "models"] and len(parts) == 5 and parts[4] == "versions":
                self._json(201, self.app.register_model_version(parts[3], body["runId"], body.get("artifactPath", "model"), body.get("description", ""), body.get("tags", {})))
            elif parts[:3] == ["api", "v1", "models"] and len(parts) == 6 and parts[4] == "aliases":
                self._json(200, self.app.set_model_alias(parts[3], parts[5], str(body["version"]), body.get("operator", "unknown"), body.get("reason", "")))
            else:
                self._json(404, {"error": "NOT_FOUND"})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except KeyError as exc:
            self._json(422, {"error": f"MISSING_FIELD:{exc.args[0]}"})
        except Exception as exc:
            traceback.print_exc()
            self._json(500, {"error": str(exc) or exc.__class__.__name__})

    def do_DELETE(self) -> None:
        try:
            path = unquote(urlparse(self.path).path)
            parts = [p for p in path.split("/") if p]
            if parts[:3] == ["api", "v1", "models"] and len(parts) == 6 and parts[4] == "aliases":
                self._json(200, self.app.delete_model_alias(parts[3], parts[5], self.headers.get("X-Cortex-User", "unknown"), "api delete"))
            else:
                self._json(404, {"error": "NOT_FOUND"})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            self._json(500, {"error": str(exc) or exc.__class__.__name__})

    def log_message(self, fmt, *args):
        return


def main() -> None:
    host = os.environ.get("CORTEX_HOST", "0.0.0.0")
    port = int(os.environ.get("CORTEX_PORT", "8000"))
    Handler.app = CortexApp.open()
    server = HTTPServer((host, port), Handler)
    print(f"cortex api listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
