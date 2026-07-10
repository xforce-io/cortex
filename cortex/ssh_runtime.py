from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Callable

from .executors.base import ArtifactSpec, ExecutionResult
from .executors.external import CapabilityExecutorWrapper
from .runtime_targets import runtime_target_connection
from .ssh_transport import create_ssh_transport


ProgressCallback = Callable[[int, str], None]


def build_remote_request(
    *,
    job: dict[str, Any],
    dataset: dict[str, Any],
    version: dict[str, Any],
    runtime_target: dict[str, Any],
    remote_job_dir: str,
    expected_git_commit: str,
    artifacts: list[dict[str, Any]],
    entrypoint: str,
    preflight_entrypoint: str | None,
    capability_name: str,
    manifest_relative_path: str,
) -> dict[str, Any]:
    return {
        "jobId": job["id"],
        "templateId": job["templateId"],
        "experimentName": job.get("experimentName") or "",
        "owner": job.get("owner") or "",
        "params": dict(job.get("params") or {}),
        "runtimeTarget": {
            "id": runtime_target.get("id"),
            "kind": runtime_target.get("kind"),
            "capabilities": list(runtime_target.get("capabilities") or []),
            "explicit": bool(runtime_target.get("explicit", True)),
        },
        "dataset": {
            "id": dataset.get("id"),
            "name": dataset.get("name"),
            "type": dataset.get("type"),
        },
        "version": {
            "id": version.get("id"),
            "datasetId": version.get("datasetId"),
            "version": version.get("version"),
            "storageUri": version.get("storageUri"),
            "checksum": version.get("checksum"),
            "format": version.get("format"),
        },
        "expectedGitCommit": expected_git_commit,
        "capabilityRoot": str(runtime_target.get("capabilityRoot") or ""),
        "workDir": remote_job_dir,
        "entrypoint": entrypoint,
        "preflightEntrypoint": preflight_entrypoint,
        "capabilityName": capability_name,
        "manifestRelativePath": manifest_relative_path,
        "artifacts": artifacts,
    }


def run_via_ssh(
    *,
    app: Any,
    job: dict[str, Any],
    dataset: dict[str, Any],
    version: dict[str, Any],
    log_path: Path,
    progress: ProgressCallback,
    executor: Any,
) -> ExecutionResult:
    target = runtime_target_connection(job.get("runtimeTarget") or {})
    if str(target.get("kind") or "") != "ssh":
        raise ValueError("RUNTIME_TARGET_NOT_CONFIGURED")
    if not target.get("host"):
        raise ValueError(f"RUNTIME_TARGET_NOT_CONFIGURED:{target.get('id') or ''}")

    work_dir_root = str(target.get("workDirRoot") or "/tmp/cortex-jobs").rstrip("/")
    remote_job_dir = f"{work_dir_root}/{job['id']}"
    capability_root = str(target.get("capabilityRoot") or "").strip()
    if not capability_root:
        raise ValueError(f"RUNTIME_TARGET_NOT_CONFIGURED:{target.get('id')}:capabilityRoot")

    wrapper = executor if isinstance(executor, CapabilityExecutorWrapper) else None
    if wrapper is None:
        raise ValueError("REMOTE_WORKER_FAILED:ssh_requires_external_executor")

    expected_git_commit = str(wrapper.spec.git_commit or "").strip()
    if not expected_git_commit:
        raise ValueError("REMOTE_WORKER_FAILED:missing_expected_git_commit")

    artifacts = [
        {
            "path": item.path,
            "target": item.target,
            "required": item.required,
            "kind": item.kind,
            "importResult": item.import_result,
        }
        for item in wrapper.spec.artifacts
    ]
    request = build_remote_request(
        job=job,
        dataset=dataset,
        version=version,
        runtime_target=target,
        remote_job_dir=remote_job_dir,
        expected_git_commit=expected_git_commit,
        artifacts=artifacts,
        entrypoint=wrapper.spec.entrypoint,
        preflight_entrypoint=wrapper.spec.preflight_entrypoint,
        capability_name=wrapper.spec.capability_name,
        manifest_relative_path=wrapper.spec.manifest_relative_path,
    )

    local_work = Path(app.home) / "jobs" / job["id"]
    local_work.mkdir(parents=True, exist_ok=True)
    local_request = local_work / "remote_request.json"
    local_result = local_work / "remote_result.json"
    local_request.write_text(json.dumps(request, indent=2, sort_keys=True), encoding="utf-8")

    progress(8, "connecting")
    transport = create_ssh_transport(target)
    try:
        try:
            transport.connect()
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"RUNTIME_TARGET_UNREACHABLE:{target.get('host')}:{exc}") from exc

        executor_ref = f"ssh:{target['id']}:{remote_job_dir}"
        app.conn.execute(
            "UPDATE training_jobs SET executor_ref = ?, status_message = ? WHERE id = ?",
            (executor_ref, "connecting", job["id"]),
        )
        app.conn.commit()

        progress(12, "preflight")
        app._update_job_progress(job["id"], 12, "preflight")
        _ensure_remote_dir(transport, remote_job_dir)
        _verify_remote_capability_revision(transport, capability_root, expected_git_commit)

        remote_request_path = f"{remote_job_dir}/request.json"
        remote_result_path = f"{remote_job_dir}/result.json"
        transport.put(local_request, remote_request_path)

        progress(25, "running")
        app._update_job_progress(job["id"], 25, "running")
        python_executable = str(target.get("pythonExecutable") or "python3")
        worker_cmd = (
            f"{shlex.quote(python_executable)} -m cortex.remote_worker "
            f"--request {shlex.quote(remote_request_path)} "
            f"--work-dir {shlex.quote(remote_job_dir)}"
        )
        worker_result = transport.run(worker_cmd)
        # Always attempt to collect result.json; failure modes are encoded there when possible.

        progress(80, "collecting")
        app._update_job_progress(job["id"], 80, "collecting")
        try:
            transport.fetch(remote_result_path, local_result)
        except ValueError as exc:
            detail = (worker_result.stderr or worker_result.stdout or str(exc)).strip()
            if worker_result.exit_code != 0:
                raise ValueError(f"REMOTE_WORKER_FAILED:{detail or worker_result.exit_code}") from exc
            raise ValueError(f"REMOTE_WORKER_FAILED:result_missing:{exc}") from exc

        payload = json.loads(local_result.read_text(encoding="utf-8"))
        if str(payload.get("status") or "") != "succeeded":
            error = str(payload.get("error") or "REMOTE_WORKER_FAILED")
            log_text = str(payload.get("logText") or "")
            if log_text:
                log_path.write_text(log_text, encoding="utf-8")
            if not error.startswith("REMOTE_") and not error.startswith("RUNTIME_"):
                error = f"REMOTE_WORKER_FAILED:{error}"
            raise ValueError(error)

        metrics = dict(payload.get("metrics") or {})
        model_payload = dict(payload.get("modelPayload") or {})
        log_text = str(payload.get("logText") or f"job {job['id']} completed on ssh target {target['id']}\n")
        log_path.write_text(log_text, encoding="utf-8")

        collected: list[ArtifactSpec] = []
        declared = payload.get("artifacts") or artifacts
        for item in declared:
            relative = str(item.get("path") or "").strip()
            if not relative:
                continue
            required = bool(item.get("required", True))
            local_artifact = local_work / relative
            remote_artifact = f"{remote_job_dir}/{relative}"
            try:
                transport.fetch(remote_artifact, local_artifact)
            except ValueError:
                if required:
                    raise ValueError(f"REMOTE_ARTIFACT_MISSING:{relative}")
                continue
            if not local_artifact.exists():
                if required:
                    raise ValueError(f"REMOTE_ARTIFACT_MISSING:{relative}")
                continue
            target_path = str(item.get("target") or f"artifacts/{Path(relative).name}")
            collected.append(ArtifactSpec(local_artifact, target_path))
            if item.get("importResult") and item.get("kind") == "prediction_result":
                dataset_ref = f"{version['datasetId']}@{version['version']}"
                app.import_prediction_result(
                    job["experimentName"],
                    job["templateId"],
                    getattr(wrapper, "model_type", ""),
                    local_artifact,
                    created_by=job.get("owner") or "unknown",
                    dataset_ref=dataset_ref,
                )

        # Also honor required artifacts from the capability contract even if remote omitted them.
        for contract in wrapper.spec.artifacts:
            if not contract.required:
                continue
            if any(spec.source.name == Path(contract.path).name or str(spec.target) == contract.target for spec in collected):
                continue
            local_artifact = local_work / contract.path
            if not local_artifact.exists():
                raise ValueError(f"REMOTE_ARTIFACT_MISSING:{contract.path}")
            collected.append(ArtifactSpec(local_artifact, contract.target))

        return ExecutionResult(metrics=metrics, model_payload=model_payload, artifacts=collected, log_text=log_text)
    finally:
        transport.close()


def _ensure_remote_dir(transport: Any, remote_job_dir: str) -> None:
    result = transport.run(f"mkdir -p {shlex.quote(remote_job_dir)}")
    if result.exit_code != 0:
        detail = (result.stderr or result.stdout or "mkdir failed").strip()
        raise ValueError(f"REMOTE_WORKER_FAILED:{detail}")


def _verify_remote_capability_revision(transport: Any, capability_root: str, expected_git_commit: str) -> None:
    command = f"git -C {shlex.quote(capability_root)} rev-parse HEAD"
    result = transport.run(command)
    if result.exit_code != 0:
        detail = (result.stderr or result.stdout or "git rev-parse failed").strip()
        raise ValueError(f"REMOTE_CAPABILITY_REVISION_MISMATCH:{detail}")
    remote_commit = (result.stdout or "").strip()
    if remote_commit != expected_git_commit:
        raise ValueError(f"REMOTE_CAPABILITY_REVISION_MISMATCH:expected={expected_git_commit},actual={remote_commit}")


