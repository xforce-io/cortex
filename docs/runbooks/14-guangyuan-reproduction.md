# Guangyuan Reproduction Runbook

This runbook is the Cortex-side operating entrypoint for hosting and
reproducing the Guangyuan multi-business LSTM experiment. It connects the
Cortex platform lifecycle to the Guangyuan-specific assets that live in
`ai-capability`.

The source of this runbook is `docs/runbooks/14-guangyuan-reproduction.md`.

## Purpose and scope

Use this runbook to verify four different paths:

- external historical result import into Cortex
- small Cortex-managed smoke reproduction
- full-training preflight failure or readiness
- resource guard visibility before long-running jobs

The runbook does not claim that full 19-business training has already been
rerun. Full training requires an explicit runtime target, prepared data, the
Guangyuan training dependencies, and an operator-owned deployment inventory
outside this repository.

## Repositories and prerequisites

Expected local repositories:

```text
/path/to/cortex
/path/to/ai-capability
```

The Cortex integration smoke expects a Python environment that can import both
Cortex and the Guangyuan capability dependencies. The current helper is:

```bash
python scripts/verify_guangyuan_smoke.py \
  --ai-capability-repo /path/to/ai-capability
```

For executor discovery outside the helper, point Cortex at the capability repo:

```bash
export CORTEX_CAPABILITY_REPOS=/path/to/ai-capability
```

Docker is not the required path for this runbook. Use it only when the local
deployment has a working daemon and the operator explicitly wants compose-based
validation.

## Known boundaries

- Cortex owns the platform lifecycle: template discovery, training jobs, run
  records, artifact collection, prediction result import, compare output,
  runtime target metadata, and resource guard records.
- `ai-capability` owns Guangyuan-specific model code, executor adapter,
  preflight logic, smoke fixture, and dataset registration helper.
- The dataset registration helper is
  `projects/guangyuan-multi-business-energy-forecast/cortex/register_dataset.py`.
- Full mode must not default to local execution. It must receive an explicit
  runtime target id that is configured on the Cortex controller.
- When `kind=ssh`, execution happens on the remote worker only; local executor
  runs must not be used to fake remote success.
- Runtime target inventory, concrete host addresses, credentials, and private
  source data paths are operational configuration. They do not belong in this
  repository.
- Existing 15 historical `pred_result.npz` files are external artifacts. They
  can be imported and compared when available, but they are not committed here.

## Dataset registration

Register the prepared Guangyuan long-table CSV with the ai-capability helper.
The CSV must contain at least:

```text
building_id
meter
timestamp
meter_reading
tree_name
```

Template command for the real prepared CSV:

```bash
python /path/to/ai-capability/projects/guangyuan-multi-business-energy-forecast/cortex/register_dataset.py \
  --source /path/to/db_full_business.csv \
  --cortex-repo /path/to/cortex \
  --cortex-home /path/to/cortex-home \
  --dataset-name guangyuan-energy-business-hourly \
  --version v2026-07-08
```

Expected output includes:

- `datasetRef`
- `checksumStatus`
- `schemaColumns`
- `sourceCsv`

Smoke fixture walkthrough:

```bash
CHECK_HOME="$(mktemp -d /tmp/cortex-guangyuan-runbook.XXXXXX)"
python /path/to/ai-capability/projects/guangyuan-multi-business-energy-forecast/cortex/register_dataset.py \
  --source /path/to/ai-capability/projects/guangyuan-multi-business-energy-forecast/fixtures/guangyuan-smoke.fixture \
  --cortex-repo /path/to/cortex \
  --cortex-home "$CHECK_HOME" \
  --dataset-name guangyuan-runbook-smoke \
  --version v1 \
  --run-smoke
```

With `--run-smoke`, the output should also include `smoke.jobId`,
`smoke.runId`, and `smoke.compareRows`.

## Existing result import

Use this path when the historical 15 `pred_result.npz` artifacts are available
outside Git. Create a manifest that points to those files:

```json
{
  "results": [
    {
      "experimentName": "guangyuan-lstm/finetune",
      "methodId": "business-a",
      "methodKind": "sequence",
      "source": "/path/to/pred_result.npz",
      "datasetRef": "guangyuan-energy-business-hourly@v2026-07-08"
    }
  ]
}
```

Import and compare:

```bash
export CORTEX_HOME=/path/to/cortex-home
python -m cortex.cli experiment-result import-manifest \
  --manifest /path/to/guangyuan-results-manifest.json \
  --created-by operator
python -m cortex.cli experiment-result compare \
  --experiment guangyuan-lstm/finetune
```

Acceptance when the external artifacts are present:

- import reports 15 successes and 0 failures
- compare returns 15 rows

If the artifact bundle is not present, record this path as external artifact
required. Do not replace it with fabricated repository-local paths.

## Smoke reproduction

The Cortex smoke helper is `scripts/verify_guangyuan_smoke.py`.

```bash
python scripts/verify_guangyuan_smoke.py \
  --ai-capability-repo /path/to/ai-capability
```

Expected output:

```text
Guangyuan Cortex smoke succeeded
resultCount: 1
compareRows: 1
```

This verifies external template loading, preflight execution, Cortex training
job completion, `predictions/pred_result.npz` collection, prediction result
import, and compare output. It is intentionally small and does not replace full
training reproduction.

## Full preflight

Full training uses `guangyuan-lstm-trainer` with `run_mode=full`. It must
receive an explicit runtime target id that is configured on the controller
(`CORTEX_RUNTIME_TARGETS`). A missing target should fail before training with:

```text
GUANGYUAN_RUNTIME_TARGET_REQUIRED
```

Other common full preflight blockers:

```text
GUANGYUAN_DEPENDENCY_MISSING:<packages>
GUANGYUAN_SOURCE_CSV_NOT_FOUND:<path>
GUANGYUAN_REQUIRED_COLUMNS_MISSING:<columns>
GUANGYUAN_NOT_ENOUGH_ROWS:<details>
GUANGYUAN_DISK_SPACE_LOW:<details>
GUANGYUAN_REMOTE_TARGET_UNAVAILABLE:<target>:<reason>
GUANGYUAN_REMOTE_PREFLIGHT_NOT_CONFIGURED:<target>
```

Full preflight should not produce `predictions/pred_result.npz` when it blocks
the job.

## Runtime target and resource guard

`runtimeTarget` is job metadata, not the executor ID. Cortex has one built-in
target, `local`. Any remote target must be supplied by controller configuration.

### SSH full job (platform dispatch)

When `runtimeTarget.kind=ssh`, Cortex treats the target as a **real execution
boundary**. The controller does not call the local executor. It opens an SSH
session, runs a one-shot remote worker, and collects structured results.

Controller configuration (never commit real values):

```bash
export CORTEX_RUNTIME_TARGETS=/path/to/.runtime-targets.json
# or inline JSON; prefer a gitignored file outside the repo
```

Example controller inventory shape (placeholders only):

```json
{
  "remote-training": {
    "kind": "ssh",
    "host": "<managed-by-deployment>",
    "user": "<managed-by-deployment>",
    "identityFile": "<managed-by-deployment>",
    "workDirRoot": "<remote-work-root>",
    "capabilityRoot": "<capability-root>",
    "pythonExecutable": "python3",
    "capabilities": ["gpu"]
  }
}
```

Submit with the target **id** only. Host, user, and key are controller-owned and
cannot be overridden from the API or job params:

```bash
export CORTEX_HOME=/path/to/cortex-home
export CORTEX_CAPABILITY_REPOS=/path/to/ai-capability
export CORTEX_RUNTIME_TARGETS=/path/to/.runtime-targets.json

python -m cortex.cli train submit \
  --template guangyuan-lstm-trainer \
  --dataset guangyuan-energy-business-hourly@v2026-07-08 \
  --experiment guangyuan-lstm/full \
  --runtime-target remote-training \
  --param run_mode=full \
  --param source_csv=<remote-data-root>/prepared/db_full_business.csv \
  --param tree_names=普通照明 \
  --param tree_vector_mode=none \
  --owner operator \
  --team ml \
  --wait
```

Stage progress for SSH jobs:

```text
connecting → preflight → running → collecting
```

Platform error codes (distinct from `GUANGYUAN_*` business codes):

```text
RUNTIME_TARGET_NOT_CONFIGURED
RUNTIME_TARGET_UNREACHABLE
REMOTE_CAPABILITY_REVISION_MISMATCH
REMOTE_WORKER_FAILED
REMOTE_ARTIFACT_MISSING
```

On any of these failures the job is `failed` and the controller must not record
a successful local training product as a substitute for remote work.

Remote environment preparation (data layout, capability checkout lock, training
dependencies) is owned by ai-capability:

- `projects/guangyuan-multi-business-energy-forecast/docs/remote-full-training.md`
- `projects/guangyuan-multi-business-energy-forecast/cortex/check_remote_prep.py`

Concrete host addresses, credentials, and private data paths stay in the
external deployment inventory. Do not commit them in source code, tests, or this
runbook. True GPU single-business acceptance remains outside this issue and is
tracked by ai-capability#12 after cortex#21 is available.

Long-running jobs can declare a resource guard in params:

```json
{
  "resource_guard": {
    "min_free_gb": 20,
    "temp_dir": "scratch",
    "cleanup_on_failure": true
  }
}
```

Local jobs should expose `resourceGuard.status=passed` when the checks pass.
Unreachable local disk requirements fail before executor execution with:

```text
RESOURCE_GUARD_FAILED:disk
```

Remote target resource checks are currently metadata-visible but skipped by
Cortex with `remote_not_checked`; remote-specific validation belongs to the
capability preflight or deployment layer.

## Artifact contract

The Guangyuan executor contract uses:

- required prediction artifact: `predictions/pred_result.npz`
- optional window artifact: `windows/F_test.npz`
- optional model artifact: `models/finetune.weights.h5`

Cortex can collect and register declared artifacts. Large artifact sync,
long-term archival, and remote artifact transfer are operational follow-up work
unless provided by the deployment.

## Troubleshooting

Dependency failure:

- Check the Python environment used by the executor.
- Install the Guangyuan training requirements in the selected environment.
- Re-run full preflight before training.

Missing columns:

- Re-run dataset registration and inspect `schemaColumns`.
- Confirm the prepared CSV includes the required long-table columns.

Not enough rows:

- Lower smoke parameters only for smoke verification.
- Do not weaken full-training thresholds to make a small fixture pass.

Runtime target missing:

- Pass an explicit runtime target for `run_mode=full`.
- Keep real target addresses and credentials in deployment configuration.

Resource guard disk failure:

- Inspect `resourceGuard` in the job response.
- Lower only the test guard threshold or select a target with enough disk.

## End-to-end verification

Run these from a clean Cortex home where possible.

1. Smoke lifecycle:

   ```bash
   python scripts/verify_guangyuan_smoke.py \
     --ai-capability-repo /path/to/ai-capability
   ```

   Verify `Guangyuan Cortex smoke succeeded`, `resultCount: 1`, and
   `compareRows: 1`.

2. Dataset registration:

   ```bash
   CHECK_HOME="$(mktemp -d /tmp/cortex-guangyuan-runbook.XXXXXX)"
   python /path/to/ai-capability/projects/guangyuan-multi-business-energy-forecast/cortex/register_dataset.py \
     --source /path/to/ai-capability/projects/guangyuan-multi-business-energy-forecast/fixtures/guangyuan-smoke.fixture \
     --cortex-repo /path/to/cortex \
     --cortex-home "$CHECK_HOME" \
     --dataset-name guangyuan-runbook-smoke \
     --version v1 \
     --run-smoke
   ```

   Verify `checksumStatus`, `schemaColumns`, `datasetRef`, and
   `smoke.compareRows`.

3. Full guard failure:

   Submit `guangyuan-lstm-trainer` with `run_mode=full` and no explicit runtime
   target. Verify `GUANGYUAN_RUNTIME_TARGET_REQUIRED` and no
   `predictions/pred_result.npz`.

4. Resource guard:

   Submit one local job with a satisfiable `resource_guard.min_free_gb` and
   verify `resourceGuard.status=passed`. Submit another with an intentionally
   impossible threshold and verify `RESOURCE_GUARD_FAILED:disk`.

5. Existing result import:

   When the external historical artifact bundle is available, import the
   manifest and compare the experiment. Verify 15/15 import success and 15
   compare rows.

## Completion checklist

- Dataset registration command recorded and validated.
- Smoke reproduction succeeds through Cortex.
- Full preflight blocker or readiness result is recorded.
- Runtime target source is explicit and external to this repository.
- Resource guard behavior is visible in job output.
- Existing historical result import is either completed or marked external
  artifact required.
- No concrete remote host address, credential, private CSV path, or runtime
  target inventory is committed.
