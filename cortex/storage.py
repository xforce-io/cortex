from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


class ObjectStorage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, uri: str) -> Path:
        if not uri.startswith("s3://"):
            raise ValueError("storageUri must use s3://bucket/path")
        bucket_and_key = uri.removeprefix("s3://")
        if "/" not in bucket_and_key:
            raise ValueError("storageUri must include a bucket and object key")
        return self.root / bucket_and_key

    def exists(self, uri: str) -> bool:
        return self.path_for(uri).exists()

    def put_file(self, uri: str, source: Path) -> None:
        target = self.path_for(uri)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def checksum(self, uri: str, data_format: str = "csv") -> str:
        path = self.path_for(uri)
        if data_format == "directory" or path.is_dir():
            return self._directory_checksum(path)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    def _directory_checksum(self, path: Path) -> str:
        if not path.is_dir():
            raise ValueError("directory checksum requires a directory object")
        digest = hashlib.sha256()
        for child in sorted(p for p in path.rglob("*") if p.is_file() and not p.name.startswith(".")):
            rel = child.relative_to(path).as_posix()
            file_digest = hashlib.sha256()
            file_digest.update(rel.encode("utf-8"))
            file_digest.update(b"\0")
            file_digest.update(child.read_bytes())
            digest.update(file_digest.digest())
        return f"sha256-dir:{digest.hexdigest()}"
