from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class SshCommandResult:
    exit_code: int
    stdout: str
    stderr: str


class SshTransport(Protocol):
    def connect(self) -> None: ...

    def run(self, command: str, timeout: float | None = None) -> SshCommandResult: ...

    def put(self, local_path: Path, remote_path: str) -> None: ...

    def fetch(self, remote_path: str, local_path: Path) -> None: ...

    def close(self) -> None: ...


TransportFactory = Callable[[dict[str, Any]], SshTransport]

_transport_factory: TransportFactory | None = None


def set_ssh_transport_factory(factory: TransportFactory | None) -> None:
    global _transport_factory
    _transport_factory = factory


def reset_ssh_transport_factory() -> None:
    set_ssh_transport_factory(None)


def create_ssh_transport(target: dict[str, Any]) -> SshTransport:
    if _transport_factory is not None:
        return _transport_factory(target)
    return SubprocessSshTransport(target)


class SubprocessSshTransport:
    def __init__(self, target: dict[str, Any]):
        host = str(target.get("host") or "").strip()
        if not host:
            raise ValueError("RUNTIME_TARGET_NOT_CONFIGURED")
        self.host = host
        self.user = str(target.get("user") or "").strip() or None
        self.port = int(target.get("port") or 22)
        self.identity_file = str(target.get("identityFile") or target.get("identity_file") or "").strip() or None
        self.connect_timeout = float(target.get("connectTimeout") or target.get("connect_timeout") or 10)
        self._connected = False

    def connect(self) -> None:
        result = self.run("true", timeout=self.connect_timeout)
        if result.exit_code != 0:
            detail = (result.stderr or result.stdout or "ssh connect failed").strip()
            raise ValueError(f"RUNTIME_TARGET_UNREACHABLE:{self.host}:{detail}")
        self._connected = True

    def run(self, command: str, timeout: float | None = None) -> SshCommandResult:
        ssh_cmd = self._ssh_base() + [self._destination(), command]
        try:
            completed = subprocess.run(
                ssh_cmd,
                check=False,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"RUNTIME_TARGET_UNREACHABLE:{self.host}:timeout") from exc
        except OSError as exc:
            raise ValueError(f"RUNTIME_TARGET_UNREACHABLE:{self.host}:{exc}") from exc
        return SshCommandResult(completed.returncode, completed.stdout or "", completed.stderr or "")

    def put(self, local_path: Path, remote_path: str) -> None:
        local = Path(local_path)
        if not local.is_file():
            raise ValueError(f"REMOTE_WORKER_FAILED:local_source_missing:{local}")
        scp_cmd = self._scp_base() + [str(local), f"{self._destination()}:{remote_path}"]
        self._run_local(scp_cmd)

    def fetch(self, remote_path: str, local_path: Path) -> None:
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)
        scp_cmd = self._scp_base() + [f"{self._destination()}:{remote_path}", str(local)]
        self._run_local(scp_cmd)

    def close(self) -> None:
        self._connected = False

    def _destination(self) -> str:
        if self.user:
            return f"{self.user}@{self.host}"
        return self.host

    def _ssh_base(self) -> list[str]:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={int(self.connect_timeout)}", "-p", str(self.port)]
        if self.identity_file:
            cmd.extend(["-i", self.identity_file])
        return cmd

    def _scp_base(self) -> list[str]:
        cmd = ["scp", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={int(self.connect_timeout)}", "-P", str(self.port)]
        if self.identity_file:
            cmd.extend(["-i", self.identity_file])
        return cmd

    def _run_local(self, cmd: list[str]) -> None:
        try:
            completed = subprocess.run(cmd, check=False, text=True, capture_output=True, timeout=self.connect_timeout + 30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"RUNTIME_TARGET_UNREACHABLE:{self.host}:{exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "scp failed").strip()
            raise ValueError(f"RUNTIME_TARGET_UNREACHABLE:{self.host}:{detail}")


@dataclass
class FakeSshTransport:
    """In-memory SSH transport for controller-side tests."""

    reachable: bool = True
    remote_git_commit: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    remote_files: dict[str, bytes] = field(default_factory=dict)
    connect_calls: int = 0
    run_calls: int = 0
    put_calls: int = 0
    fetch_calls: int = 0
    commands: list[str] = field(default_factory=list)

    def connect(self) -> None:
        self.connect_calls += 1
        if not self.reachable:
            raise ValueError("RUNTIME_TARGET_UNREACHABLE:fake:connection refused")

    def run(self, command: str, timeout: float | None = None) -> SshCommandResult:
        self.run_calls += 1
        self.commands.append(command)
        if not self.reachable:
            return SshCommandResult(255, "", "connection refused")

        if "rev-parse HEAD" in command:
            return SshCommandResult(0, f"{self.remote_git_commit}\n", "")

        if "mkdir -p" in command:
            return SshCommandResult(0, "", "")

        if "cortex.remote_worker" in command or "remote_worker" in command:
            return self._handle_worker(command)

        return SshCommandResult(0, "", "")

    def put(self, local_path: Path, remote_path: str) -> None:
        self.put_calls += 1
        self.remote_files[remote_path] = Path(local_path).read_bytes()

    def fetch(self, remote_path: str, local_path: Path) -> None:
        self.fetch_calls += 1
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)
        # Support result.json and artifact paths populated by worker simulation.
        if remote_path in self.remote_files:
            local.write_bytes(self.remote_files[remote_path])
            return
        # basename match for artifact files staged by result.artifactFiles
        name = Path(remote_path).name
        for key, value in self.remote_files.items():
            if Path(key).name == name or key.endswith(remote_path):
                local.write_bytes(value)
                return
        raise ValueError(f"REMOTE_ARTIFACT_MISSING:{remote_path}")

    def close(self) -> None:
        return None

    def _handle_worker(self, command: str) -> SshCommandResult:
        payload = dict(self.result or {})
        status = str(payload.get("status") or "succeeded")
        # Stage result.json and artifacts for subsequent fetch calls.
        # Controllers put request under <workDir>/request.json and expect result.json next to it.
        work_dir = self._extract_work_dir(command)
        result_doc = {
            "status": status,
            "metrics": payload.get("metrics") or {},
            "modelPayload": payload.get("modelPayload") or {},
            "logText": payload.get("logText") or "",
            "error": payload.get("error"),
            "artifacts": payload.get("artifacts") or [],
        }
        result_path = f"{work_dir}/result.json"
        self.remote_files[result_path] = __import__("json").dumps(result_doc).encode("utf-8")
        artifact_files = payload.get("artifactFiles") or {}
        for relative, content in artifact_files.items():
            data = content if isinstance(content, (bytes, bytearray)) else str(content).encode("utf-8")
            self.remote_files[f"{work_dir}/{relative}"] = bytes(data)
            self.remote_files[relative] = bytes(data)
        if status != "succeeded":
            # Worker process non-zero exit is optional; controller primarily reads result.json.
            return SshCommandResult(1, "", str(payload.get("error") or "REMOTE_WORKER_FAILED"))
        return SshCommandResult(0, "remote worker ok\n", "")

    def _extract_work_dir(self, command: str) -> str:
        # Expect: ... --work-dir <dir> or request path under work dir.
        tokens = shlex.split(command)
        if "--work-dir" in tokens:
            index = tokens.index("--work-dir")
            if index + 1 < len(tokens):
                return tokens[index + 1]
        if "--request" in tokens:
            index = tokens.index("--request")
            if index + 1 < len(tokens):
                return str(Path(tokens[index + 1]).parent)
        return "/tmp/cortex-remote-job"
