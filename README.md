# Cortex

Cortex is a local ML platform prototype for exercising the core workflow from dataset registration to training, experiment tracking, model registration, and evaluation.

The implementation is intentionally small and file-backed:

- SQLite for Cortex metadata.
- File-backed `s3://` object storage under `CORTEX_HOME/objects`.
- A local MLflow-compatible tracking and model registry store under `CORTEX_HOME/mlruns`.
- A local executor for runnable sklearn templates.
- A static web console served by the Cortex API.

## Quick Start

From a clean checkout, create a virtual environment and install the package first:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

```bash
export CORTEX_HOME=.cortex
export CORTEX_HOST=127.0.0.1
export CORTEX_PORT=8768
python -m cortex.api
```

Open:

```text
http://127.0.0.1:8768/
```

Use `127.0.0.1` rather than opening `web/index.html` directly. The API server serves the web assets and keeps browser requests on the same origin.

## Web Console

The console exposes the current end-to-end workflow:

- Dashboard summary cards for Datasets, Jobs, Runs, Models, and Tests. Each card navigates to the related resource page.
- Resource tables for Datasets, Training Jobs, Experiments, Models, and Evaluations. Long tables show the latest 5 rows by default with `View more`.
- Clickable rows with detail panels for dataset versions, job progress/logs, run metrics/artifacts, model versions, and evaluation metrics.
- Training job submission with executable template filtering.
- Running job progress with status messages.
- Experiment detail with model artifact visibility.
- `Register as model` flow from a completed run into the model registry.
- Model alias support for `champion` and `challenger`.
- Evaluation flow for registered model versions against test datasets.

If the workspace is empty, click `Create example workspace` on the Dashboard. It creates sample KMeans, slow KMeans, and regression datasets so the full workflow can be exercised from the UI.

## Supported Training Templates

Templates are seeded into the `training_templates` table on database initialization. The UI only shows templates whose executor is implemented.

| Template | Task | Dataset type | Params | Executor |
| --- | --- | --- | --- | --- |
| `sklearn-kmeans` | clustering | `tabular` | `n_clusters`, `random_state` | available |
| `sklearn-regressor` | regression | `tabular` | `target` | available |
| `sklearn-classifier` | classification | `tabular` | `target` | not implemented |
| `statsmodels-mstl` | forecasting | `time_series` | `periods`, `value_column`, `time_column`, `trend`, `max_iter` | available |
| `pytorch-sequence-forecast` | forecasting | `time_series` | `time_column`, `target_column`, `window`, `horizon`, `epochs` | available with PyTorch |
| `pytorch-basic` | training | `tabular`, `time_series` | `epochs` | not implemented |

`sklearn-kmeans` writes a `model/model.json` artifact containing cluster centers and logs `inertia` and `rows`.

`sklearn-regressor` is a lightweight linear regressor. It requires `target` to name a numeric target column, uses the other numeric columns as features, writes a `model/model.json` artifact, and logs `mae`, `rmse`, `r2`, and `rows`. Invalid target data fails explicitly, for example `TARGET_REQUIRED`, `TARGET_COLUMN_NOT_FOUND`, or `TARGET_MUST_BE_NUMERIC`.

## Typical UI Flow

1. Open the console and create the example workspace if needed.
2. Go to `Training`.
3. Click `New training job`.
4. Choose `sklearn KMeans` or `sklearn regressor`.
5. Pick a compatible dataset version.
6. Submit the job and watch progress in the jobs table and job detail.
7. Click `View training results` to inspect the experiment run.
8. Click `Register as model` to create a model version.
9. Optionally set the registered version as `champion` or `challenger`.
10. Evaluate a registered model version against an evaluation dataset.

## CLI

```bash
export CORTEX_HOME=.cortex
python -m cortex.cli train templates
```

Example training submission:

The example below expects the demo workspace to exist. Create it from the Dashboard with `Create example workspace`, or call:

```bash
curl --noproxy '*' -X POST http://127.0.0.1:8768/api/v1/demo/full-test \
  -H 'Content-Type: application/json' \
  -d '{}'
```

```bash
python -m cortex.cli train submit \
  --template sklearn-kmeans \
  --dataset ds_e2e_blobs@v1 \
  --experiment demo/example \
  --param n_clusters=3 \
  --owner alice \
  --team ml \
  --wait
```

## API

```bash
export CORTEX_HOME=.cortex
export CORTEX_HOST=127.0.0.1
export CORTEX_PORT=8768
python -m cortex.api
curl --noproxy '*' http://127.0.0.1:8768/healthz
curl --noproxy '*' http://127.0.0.1:8768/api/v1/dashboard
```

Useful endpoints:

- `GET /healthz`
- `GET /api/v1/dashboard`
- `GET /api/v1/training/templates`
- `POST /api/v1/training/jobs`
- `GET /api/v1/training/jobs/{job_id}`
- `GET /api/v1/runs/{run_id}`
- `POST /api/v1/models/{name}/versions`
- `POST /api/v1/models/{name}/aliases/{alias}`
- `POST /api/v1/evaluations`
- `POST /api/v1/demo/full-test`

## Tests

```bash
python -m pip install pytest torch
python -m pytest tests/test_phase1_stories.py -q
```

The suite covers dataset registration, executable template filtering, KMeans training, regression training, bad regression target handling, job progress, model registration, alias audit, evaluation, API flow, and static web console assets.

The compose validation test requires Docker:

```bash
docker compose -f deploy/docker-compose.yml config
docker compose -f deploy/docker-compose.yml up --build
```
