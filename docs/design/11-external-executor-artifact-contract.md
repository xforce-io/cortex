# External Executor Artifact Contract

Issue: #11

## Goal

Define artifact collection for external executors loaded from capability manifests. The platform keeps the existing training lifecycle and `ExecutionResult.artifacts` behavior, but lets an external manifest declare files that must exist after `executor.run(context)` completes.

This design is a platform contract only. Guangyuan-specific executor wiring remains in #12.

## Manifest Contract

Add optional `artifacts` under each `executors[]` item:

```yaml
executors:
  - id: external-lstm
    name: External LSTM
    model_type: python
    dataset_types: [time_series]
    entrypoint: python:src.executor:Executor
    param_schema: {}
    artifacts:
      - path: outputs/model.keras
        target: model/model.keras
        required: true
        kind: model
      - path: outputs/pred_result.npz
        target: predictions/pred_result.npz
        required: true
        kind: prediction_result
        import_result: true
      - path: outputs/eval_summary.csv
        target: reports/eval_summary.csv
        required: false
        kind: report
```

Rules:

- `path` is required and resolved relative to `context.work_dir`.
- `target` is optional and defaults to `artifacts/{basename}`.
- `required` defaults to `true`.
- `kind` defaults to `artifact`; supported values are `artifact`, `model`, `prediction_result`, `report`, `metrics`.
- `import_result` defaults to `false` and is only valid for `kind=prediction_result`.

## Runtime Behavior

After `executor.run(context)` returns:

1. The wrapper validates expected artifacts.
2. Required missing files fail the job with `EXECUTOR_ARTIFACT_MISSING:{path}`.
3. Optional missing files are skipped.
4. Present files are appended to `ExecutionResult.artifacts`, so existing Cortex/MLflow artifact logging remains the single storage path.
5. `kind=prediction_result` with `import_result=true` calls existing `import_prediction_result()` using:
   - `experimentName = job.experimentName`
   - `methodId = executor template id`
   - `methodKind = executor model type`
   - `datasetRef = datasetId@version`
   - `createdBy = job.owner`

## Non-Goals

- No container orchestration or resource scheduler.
- No framework-specific artifact conventions.
- No parsing arbitrary metrics CSV into experiment result rows.
- No broad changes to built-in executors.
- No Guangyuan-specific paths hardcoded in Cortex.

## Test Plan

Unit and functional tests:

- Manifest artifact schema validates required `path` and supported `kind`.
- A fixture external executor writes declared artifacts under `context.work_dir`; Cortex logs them as run artifacts.
- A declared required missing artifact fails the job with a clear error.
- Optional missing artifacts do not fail the job.

End-to-end tests:

- Load a temporary capability repo with an external executor that writes `outputs/model.txt`, `outputs/pred_result.npz`, and `outputs/eval_summary.csv`.
- Submit a Cortex training job for that external executor.
- Assert run artifacts include the declared targets.
- Assert `pred_result.npz` is imported into experiment results when `import_result=true`.
- Assert a missing required artifact fixture fails and leaves the missing path in the job error/logs.
