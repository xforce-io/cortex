# Batch Import Prediction Results

Issue: #9

## Goal

Add a batch import path for external prediction result NPZ files while reusing the existing single-result `import_prediction_result()` validation, metric calculation, storage, audit, and dashboard behavior.

This design defines the generic platform import contract only. Guangyuan-specific runbook wording, external executor wrapping, and comparison UI remain in follow-up issues.

## Manifest Contract

The batch input is a JSON manifest with a top-level `results` array. Each item maps directly to one prediction result import:

```json
{
  "results": [
    {
      "experimentName": "guangyuan/lstm",
      "methodId": "pretrain-finetune-store-a",
      "methodKind": "external-lstm",
      "source": "/absolute/path/to/pred_result.npz",
      "datasetRef": "optional-dataset-ref",
      "createdBy": "alice",
      "tags": ["optional"],
      "notes": "optional human note"
    }
  ]
}
```

Required per item:

- `experimentName`
- `methodId`
- `source`

Optional per item:

- `methodKind`
- `datasetRef`
- `createdBy`
- `tags`
- `notes`

`source` is resolved relative to the manifest file directory when it is not absolute. This keeps downloaded experiment folders portable.

## Batch Semantics

- Import entries independently and keep processing after item-level failures.
- Reuse existing NPZ checks: file exists, `.npz` format, `y_true` and `y_pred` arrays exist, arrays are non-empty and equal length.
- Return a structured summary with counts plus per-item success/failure records.
- Each successful item returns the created experiment result.
- Each failed item returns its manifest index, source, method id if present, and error code.

Response shape:

```json
{
  "total": 3,
  "succeeded": 2,
  "failed": 1,
  "results": [
    {"index": 0, "status": "succeeded", "result": {"id": "er_..."}},
    {"index": 1, "status": "failed", "error": "PREDICTION_ARRAYS_REQUIRED", "source": "bad.npz"}
  ]
}
```

## Idempotency

Batch import is append-only, matching the current single import behavior. Re-importing the same manifest creates new experiment result rows and new artifact URIs.

Existing results are immutable experiment observations. Deduping or overwrite semantics need a separate identity model and conflict policy, which is outside this issue.

## Interfaces

- Core API: `CortexApp.import_prediction_results_manifest(manifest, created_by="unknown")`
- CLI: `cortex experiment-result import-manifest --manifest path.json [--created-by alice]`
- HTTP API: `POST /api/v1/experiment-results:import-manifest` with `{ "manifest": "path/to/manifest.json", "createdBy": "alice" }`

## Non-Goals

- No CSV metric-table parsing.
- No workflow engine.
- No result overwrite or dedupe.
- No Guangyuan-specific field hardcoding.
- No comparison or ranking view; that belongs to #10.

## Test Plan

Unit and functional tests:

- Manifest requires a top-level `results` array.
- Relative `source` paths resolve from the manifest directory.
- One invalid NPZ does not prevent valid entries from importing.
- Returned summary includes total, succeeded, failed, and per-item error details.

End-to-end tests:

- Create a temporary Cortex home with a manifest containing valid and invalid fixture NPZ files.
- Import via CLI and assert the process exits successfully, the response reports successes and failures, and `experiment-result list` shows imported results with computed metrics.
- Exercise the HTTP API import endpoint against a local server and assert the same lifecycle-critical path: request, import, list visibility.
