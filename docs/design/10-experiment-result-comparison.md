# Experiment Result Comparison

Issue: #10

## Goal

Add a generic comparison read model for imported or platform-generated experiment results. The comparison groups rows by one `experimentName` and returns method-level metric rows that can be consumed by CLI/API and, later, Web UI.

This design does not introduce Guangyuan-specific ranking rules. It only exposes a stable platform comparison shape over existing `experiment_results` rows.

## Contract

Core API:

```python
CortexApp.compare_experiment_results(
    experiment_name: str,
    dataset_ref: str = "",
    method_kind: str = "",
    sort_by: str = "rmse",
    sort_order: str = "asc",
) -> dict
```

HTTP API:

```text
GET /api/v1/experiment-results:compare?experimentName=...&datasetRef=...&methodKind=...&sortBy=rmse&sortOrder=asc
```

CLI:

```text
cortex experiment-result compare --experiment NAME [--dataset-ref REF] [--method-kind KIND] [--sort-by rmse] [--sort-order asc]
```

Response shape:

```json
{
  "experimentName": "guangyuan/lstm",
  "datasetRef": "",
  "methodKind": "",
  "sortBy": "rmse",
  "sortOrder": "asc",
  "rows": [
    {
      "rank": 1,
      "resultId": "er_...",
      "methodId": "mstl-baseline",
      "methodKind": "sequence",
      "datasetRef": "meter@v1",
      "createdAt": "...",
      "metrics": {"rows": 100, "rmse": 1.2, "mae": 0.8, "r2": 0.91, "cv": 0.12, "mape": 4.5},
      "best": {"rmse": true, "mae": true, "r2": false, "cv": true, "mape": true}
    }
  ]
}
```

## Sorting And Best Markers

- Default sort is `rmse asc`.
- Supported sort fields: `rmse`, `mae`, `r2`, `cv`, `mape`, `rows`, `createdAt`, `methodId`.
- Lower is better for `rmse`, `mae`, `cv`, and `mape`.
- Higher is better for `r2` and `rows`.
- Missing numeric metrics sort last and never receive a best marker.
- Ties can all receive the same best marker for the metric.
- `rank` is display order after sorting, not a statistical rank.

## Filtering

- `experimentName` is required.
- `datasetRef` and `methodKind` are optional exact-match filters.
- There is no fuzzy grouping or Guangyuan method taxonomy in this issue.

## Non-Goals

- No statistical significance tests.
- No business-specific metric weighting.
- No dedupe or latest-only semantics; append-only result identity from #9 remains visible.
- No new storage table; this is a read model over `experiment_results`.

## Test Plan

Unit and functional tests:

- Multiple results under one experiment are sorted by default `rmse asc`.
- Best markers handle lower-is-better and higher-is-better metrics correctly.
- Missing metrics sort last and do not become best.
- `datasetRef` and `methodKind` filters are exact-match filters.

End-to-end tests:

- Import multiple fixture NPZ files with #9 manifest batch import.
- Call the comparison API and assert it returns multiple method rows, sorted metrics, rank, and best markers.
- Call the CLI compare command and assert it returns the same lifecycle-critical comparison shape.
