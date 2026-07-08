# Generic Sequence Forecasting Executor

## Goal

Add an executable, generic sequence forecasting template to Cortex so sequence experiments can run inside the platform instead of only being imported as external prediction artifacts.

## Template

The executor adds `pytorch-sequence-forecast` for `time_series` datasets.

Template parameters are user-provided and schema-neutral:

- `time_column`: column containing orderable timestamps or sequence positions.
- `target_column`: numeric target to forecast.
- `group_column`: optional grouping key for independent sequences.
- `feature_columns`: optional comma-separated input features. When omitted, target history is used.
- `window`: lookback length.
- `horizon`: forecast horizon.
- `epochs`: training epochs.
- `learning_rate`: optimizer learning rate.
- `hidden_size`: LSTM hidden size.
- `seed`: deterministic training seed.
- `validation_ratio`: time-ordered validation split ratio.
- `warm_start_model`: optional registered model reference in `name:version` form.

The template must not hardcode domain fields, private schema, local file names, observed dataset characteristics, or metric values.

## Executor Behavior

1. Resolve the dataset version through the existing dataset registry and object storage.
2. Validate that required mappings exist and mapped target/features are numeric.
3. Build sliding-window supervised samples per group when `group_column` is provided, otherwise as one sequence.
4. Split train and validation windows by time order.
5. Train a compact PyTorch sequence regressor: LSTM encoder plus linear forecast head.
6. If `warm_start_model` is provided, load compatible weights from a registered sequence model and continue training.
7. Persist `model/model.json` and `model/model.pt` as run artifacts.
8. Persist validation predictions as a generic experiment result so Results can rank the method with imported and baseline results.

## Data Contract

Prediction artifacts use generic arrays:

- `y_true`
- `y_pred`

Model metadata stores generic mappings, hyperparameters, normalization parameters, and metric summaries. It does not store private sample rows.

## Failure Modes

- `PYTORCH_NOT_AVAILABLE`
- `SEQUENCE_TIME_COLUMN_REQUIRED`
- `SEQUENCE_TARGET_COLUMN_REQUIRED`
- `SEQUENCE_TIME_COLUMN_NOT_FOUND`
- `SEQUENCE_TARGET_COLUMN_NOT_FOUND`
- `SEQUENCE_GROUP_COLUMN_NOT_FOUND`
- `SEQUENCE_TARGET_MUST_BE_NUMERIC`
- `SEQUENCE_FEATURE_COLUMN_NOT_FOUND`
- `SEQUENCE_FEATURE_MUST_BE_NUMERIC`
- `SEQUENCE_INVALID_WINDOW`
- `SEQUENCE_INVALID_HORIZON`
- `SEQUENCE_INVALID_EPOCHS`
- `SEQUENCE_INVALID_HIDDEN_SIZE`
- `SEQUENCE_INVALID_LEARNING_RATE`
- `SEQUENCE_INVALID_VALIDATION_RATIO`
- `SEQUENCE_NOT_ENOUGH_WINDOWS`
- `SEQUENCE_WARM_START_INVALID`
- `SEQUENCE_WARM_START_NOT_FOUND`
- `SEQUENCE_WARM_START_INCOMPATIBLE`

## Test Plan

Use synthetic time-series data only.

- Template is executable.
- Scratch training succeeds and writes run metrics, model artifacts, and experiment results.
- Missing required mappings fail explicitly.
- Warm-start fine-tuning from a compatible registered model succeeds.
- Incompatible warm-start artifacts fail explicitly.
- Existing MSTL and prediction-result import behavior remains green.

## Out of Scope

- GPU scheduling.
- Distributed training.
- Domain-specific feature discovery.
- Private dataset fixtures or experimental records in git.
