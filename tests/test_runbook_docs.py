import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "runbooks" / "14-guangyuan-reproduction.md"
README = ROOT / "README.md"


def test_guangyuan_runbook_is_linked_from_readme():
    readme = README.read_text(encoding="utf-8")

    assert "docs/runbooks/14-guangyuan-reproduction.md" in readme
    assert RUNBOOK.is_file()


def test_guangyuan_runbook_covers_lifecycle_paths():
    text = RUNBOOK.read_text(encoding="utf-8")
    required_phrases = [
        "Purpose and scope",
        "Known boundaries",
        "Dataset registration",
        "Existing result import",
        "Smoke reproduction",
        "Full preflight",
        "Runtime target and resource guard",
        "SSH full job",
        "Artifact contract",
        "End-to-end verification",
        "Completion checklist",
        "scripts/verify_guangyuan_smoke.py",
        "projects/guangyuan-multi-business-energy-forecast/cortex/register_dataset.py",
        "projects/guangyuan-multi-business-energy-forecast/docs/remote-full-training.md",
        "GUANGYUAN_RUNTIME_TARGET_REQUIRED",
        "RUNTIME_TARGET_NOT_CONFIGURED",
        "RUNTIME_TARGET_UNREACHABLE",
        "REMOTE_CAPABILITY_REVISION_MISMATCH",
        "REMOTE_WORKER_FAILED",
        "REMOTE_ARTIFACT_MISSING",
        "CORTEX_RUNTIME_TARGETS",
        "connecting → preflight → running → collecting",
        "RESOURCE_GUARD_FAILED:disk",
        "predictions/pred_result.npz",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_guangyuan_runbook_references_existing_repo_entrypoints():
    text = RUNBOOK.read_text(encoding="utf-8")
    expected_paths = {
        "scripts/verify_guangyuan_smoke.py",
        "docs/runbooks/14-guangyuan-reproduction.md",
    }

    for path in expected_paths:
        assert path in text
        assert (ROOT / path).exists()


def test_guangyuan_runbook_does_not_commit_runtime_inventory_or_secrets():
    combined = README.read_text(encoding="utf-8") + "\n" + RUNBOOK.read_text(encoding="utf-8")
    forbidden_patterns = [
        r"192\.168\.20\.144",
        r"\bgpu" + r"-3090\b",
        "PRIVATE" + "-TOKEN",
        r"gitlab api token",
    ]

    for pattern in forbidden_patterns:
        assert not re.search(pattern, combined)
