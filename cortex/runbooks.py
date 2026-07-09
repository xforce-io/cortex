from __future__ import annotations

from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK_ROOT = ROOT / "docs" / "runbooks"


def _runbook_id(path: Path) -> str:
    name = path.stem
    parts = name.split("-", 1)
    if len(parts) == 2 and parts[0].isdigit():
        return name
    return name


def _title(lines: list[str], fallback: str) -> str:
    for line in lines:
        if line.startswith("# "):
            return line.removeprefix("# ").strip()
    return fallback


def _sections(lines: list[str]) -> list[str]:
    sections: list[str] = []
    for line in lines:
        if line.startswith("## "):
            section = line.removeprefix("## ").strip()
            if section:
                sections.append(section)
    return sections


def _summary(lines: list[str]) -> str:
    paragraphs: list[str] = []
    current: list[str] = []
    in_code = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or stripped.startswith("#"):
            continue
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if stripped.startswith("- "):
            continue
        current.append(stripped)
        if len(" ".join(current)) >= 220:
            break
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs[0] if paragraphs else ""


def _public_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _read(path: Path, include_content: bool = False) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    item = {
        "id": _runbook_id(path),
        "title": _title(lines, path.stem),
        "path": _public_path(path),
        "summary": _summary(lines),
        "sections": _sections(lines),
        "updatedAt": path.stat().st_mtime,
    }
    if include_content:
        item["content"] = text
    return item


def list_runbooks() -> list[dict[str, Any]]:
    if not RUNBOOK_ROOT.is_dir():
        return []
    return [_read(path) for path in sorted(RUNBOOK_ROOT.glob("*.md")) if path.is_file()]


def get_runbook(runbook_id: str) -> dict[str, Any]:
    for path in sorted(RUNBOOK_ROOT.glob("*.md")) if RUNBOOK_ROOT.is_dir() else []:
        if path.is_file() and _runbook_id(path) == runbook_id:
            return _read(path, include_content=True)
    raise ValueError(f"RUNBOOK_NOT_FOUND:{runbook_id}")
