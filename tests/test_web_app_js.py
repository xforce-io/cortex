import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebAppJsTest(unittest.TestCase):
    def run_app_script(self, test_code: str) -> None:
        source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        harness = r"""
const assert = require("assert");

function createElement(selector) {
  return {
    selector,
    className: "",
    hidden: false,
    innerHTML: "",
    textContent: "",
    value: "",
    disabled: false,
    dataset: {},
    style: {},
    classList: {
      toggle() {},
      add() {},
      remove() {},
    },
    addEventListener() {},
    querySelector() {
      return createElement("child");
    },
    getContext() {
      return {
        clearRect() {},
        fillText() {},
        beginPath() {},
        arc() {},
        fill() {},
        fillRect() {},
        lineTo() {},
        moveTo() {},
        stroke() {},
      };
    },
  };
}

const elements = new Map();
function elementFor(selector) {
  if (!elements.has(selector)) elements.set(selector, createElement(selector));
  return elements.get(selector);
}

global.window = { location: { protocol: "http:", origin: "http://127.0.0.1:8768" } };
global.localStorage = {
  getItem() {
    return null;
  },
  setItem() {},
};
global.document = {
  documentElement: createElement("html"),
  body: createElement("body"),
  querySelector: elementFor,
  querySelectorAll() {
    return [];
  },
  addEventListener() {},
};
global.fetch = async (url) => ({
  ok: true,
  json: async () => {
    if (String(url).endsWith("/healthz")) return { ok: true };
    return {
      summary: { datasets: 0, jobs: 0, runs: 0, models: 0, evaluations: 0, experimentResults: 0 },
      datasets: [],
      jobs: [],
      runs: [],
      models: [],
      evaluations: [],
      experimentResults: [],
      projects: [],
    };
  },
  text: async () => "",
});
"""
        script = harness + "\n" + source + "\n(async () => {\n" + textwrap.dedent(test_code) + "\n})().catch((error) => { console.error(error); process.exit(1); });\n"
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True)
        if result.returncode != 0:
            self.fail(result.stderr or result.stdout)

    def test_training_job_dataset_version_jumps_to_owning_dataset(self):
        self.run_app_script(
            r"""
state.currentProjectId = "proj_default";
state.dashboard = {
  project: { id: "proj_default", name: "Default" },
  summary: { datasets: 1, jobs: 1, runs: 0, models: 0, evaluations: 0, experimentResults: 0 },
  datasets: [
    {
      id: "ds_real_repro",
      name: "real-repro",
      description: "baseline data",
      type: "time_series",
      versionCount: 1,
      latestVersion: "v1",
      owner: "alice",
      team: "ml",
      domain: "",
      sourceSystem: "",
      visibility: "team",
      tags: [],
      status: "active",
      createdAt: "2026-07-06T00:00:00Z",
      updatedAt: "2026-07-06T00:00:00Z",
    },
  ],
  jobs: [
    {
      id: "job_70b1611d0179",
      templateId: "statsmodels-mstl",
      projectId: "proj_default",
      status: "succeeded",
      progressPercent: 100,
      statusMessage: "Completed",
      datasetVersionId: "dv_fa6526970275",
      mlflowRunId: "",
      experimentName: "real-repro/traditional-baseline",
      owner: "local",
      params: {},
    },
  ],
  runs: [],
  models: [],
  evaluations: [],
  experimentResults: [],
};
state.selected.job = "job_70b1611d0179";
state.details["dataset:ds_real_repro"] = {
  versions: [{ id: "dv_fa6526970275", datasetId: "ds_real_repro", version: "v1", format: "csv", storageUri: "s3://datasets/real-repro/v1/train.csv", checksumStatus: "verified" }],
  lineage: [],
};

const target = findDatasetVersionTarget("dv_fa6526970275");
assert.deepStrictEqual(target, { datasetId: "ds_real_repro", versionId: "dv_fa6526970275", version: "v1" });

renderJobDetail();
assert.match(elementFor("#jobDetail").innerHTML, /data-jump-dataset-version="dv_fa6526970275"/);

await jumpToDatasetVersion("dv_fa6526970275");
assert.strictEqual(state.activeView, "datasets");
assert.strictEqual(state.selected.dataset, "ds_real_repro");
assert.match(elementFor("#datasetsBody").innerHTML, /class="selectable-row selected" data-resource-type="dataset" data-resource-id="ds_real_repro"/);
"""
        )

    def test_unresolved_dataset_version_remains_plain_text(self):
        self.run_app_script(
            r"""
state.dashboard = {
  summary: { datasets: 0, jobs: 1, runs: 0, models: 0, evaluations: 0, experimentResults: 0 },
  datasets: [],
  jobs: [{ id: "job_missing", templateId: "statsmodels-mstl", status: "succeeded", progressPercent: 100, datasetVersionId: "dv_missing", experimentName: "missing", owner: "local", params: {} }],
  runs: [],
  models: [],
  evaluations: [],
  experimentResults: [],
};
state.selected.job = "job_missing";

assert.strictEqual(findDatasetVersionTarget("dv_missing"), null);
renderJobDetail();
assert.match(elementFor("#jobDetail").innerHTML, /<span class="mono">dv_missing<\/span>/);
assert.doesNotMatch(elementFor("#jobDetail").innerHTML, /data-jump-dataset-version/);
"""
        )

    def test_runbook_view_renders_list_detail_and_markdown(self):
        self.run_app_script(
            r"""
state.runbooks.items = [
  {
    id: "14-guangyuan-reproduction",
    title: "Guangyuan Reproduction Runbook",
    path: "docs/runbooks/14-guangyuan-reproduction.md",
    summary: "This runbook is the Cortex-side operating entrypoint.",
    sections: ["Smoke reproduction", "Full preflight", "Runtime target and resource guard"],
    updatedAt: "2026-07-09T00:00:00Z",
  },
];
state.runbooks.selectedId = "14-guangyuan-reproduction";
state.runbooks.details["14-guangyuan-reproduction"] = {
  ...state.runbooks.items[0],
  content: "# Guangyuan Reproduction Runbook\n\n## Smoke reproduction\n\nUse `scripts/verify_guangyuan_smoke.py`.\n\n```text\nGUANGYUAN_RUNTIME_TARGET_REQUIRED\n```\n",
};

renderRunbooks();

assert.match(elementFor("#runbookCount").textContent, /1/);
assert.match(elementFor("#runbooksBody").innerHTML, /Guangyuan Reproduction Runbook/);
assert.match(elementFor("#runbookDetail").innerHTML, /docs\/runbooks\/14-guangyuan-reproduction\.md/);
assert.match(elementFor("#runbookDetail").innerHTML, /Smoke reproduction/);
assert.match(elementFor("#runbookDetail").innerHTML, /GUANGYUAN_RUNTIME_TARGET_REQUIRED/);
assert.match(renderMarkdown("# Title\n\n- one\n\n```text\ncode\n```"), /<h1>Title<\/h1>/);
assert.match(renderMarkdown("# Title\n\n- one\n\n```text\ncode\n```"), /<li>one<\/li>/);
assert.match(renderMarkdown("# Title\n\n- one\n\n```text\ncode\n```"), /<pre class="detail-json"><code>code/);
"""
        )

    def test_dataset_detail_surfaces_version_preview_and_project_unlink_scope(self):
        self.run_app_script(
            r"""
state.currentProjectId = "proj_default";
state.dashboard = {
  project: { id: "proj_default", name: "Default" },
  summary: { datasets: 1, jobs: 0, runs: 0, models: 0, evaluations: 0, experimentResults: 0 },
  datasets: [
    {
      id: "ds_customer_features",
      name: "customer-features",
      description: "Reusable customer features",
      type: "tabular",
      versionCount: 1,
      latestVersion: "v1",
      owner: "alice",
      team: "ml",
      domain: "crm",
      sourceSystem: "warehouse",
      visibility: "team",
      tags: ["golden"],
      status: "active",
      createdAt: "2026-07-06T00:00:00Z",
      updatedAt: "2026-07-06T00:00:00Z",
      projectLink: { id: "pdl_1", role: "train", versionPolicy: "latest", pinnedVersion: null },
    },
  ],
  jobs: [],
  runs: [],
  models: [],
  evaluations: [],
  experimentResults: [],
};
state.selected.dataset = "ds_customer_features";
state.details["dataset:ds_customer_features"] = {
  versions: [
    {
      id: "dv_customer_v1",
      datasetId: "ds_customer_features",
      version: "v1",
      format: "csv",
      storageUri: "s3://datasets/customer-features/v1/data.csv",
      rowCount: 2,
      checksumStatus: "verified",
      trainable: true,
      approvalStatus: "approved",
      schema: { columns: [{ name: "customer_id", type: "string" }] },
    },
  ],
  lineage: [],
  selectedPreview: "v1",
  preview: {
    "v1": {
      rows: [{ customer_id: "c_001" }, { customer_id: "c_002" }],
      schema: { columns: [{ name: "customer_id", type: "string" }] },
      storageUri: "s3://datasets/customer-features/v1/data.csv",
      profile: { rows: 2, columns: 1 },
      truncated: false,
    },
  },
};

renderDatasetDetail();
const html = elementFor("#datasetDetail").innerHTML;
assert.match(html, /dataset-asset-summary/);
assert.match(html, /data-use-dataset-version="ds_customer_features@v1"/);
assert.ok(html.indexOf("dataset-asset-summary") < html.indexOf("data-dataset-metadata-form"));
assert.match(html, /Reusable customer features/);
assert.match(html, /ds_customer_features/);
assert.match(html, /最新 v1/);
assert.match(html, /verified/);
assert.match(html, /trainable/);
assert.match(html, /approved/);
assert.match(html, /DatasetVersion/);
assert.match(html, /data-preview-dataset-version="v1"/);
assert.match(html, /收起预览/);
assert.match(html, /preview-panel framed-panel/);
assert.match(html, /data-close-dataset-preview/);
assert.match(html, /data-use-dataset-version="ds_customer_features@v1"/);
assert.match(html, /data-unlink-project-dataset="ds_customer_features"/);
assert.doesNotMatch(html, /data-archive-dataset/);
assert.doesNotMatch(html, /data-restore-dataset/);
assert.doesNotMatch(html, /Delete dataset/);
assert.match(html, /DatasetVersion v1 · s3:\/\/datasets\/customer-features\/v1\/data.csv · 行数 2 · 1 columns/);
assert.match(html, /customer_id/);
assert.match(html, /string/);
assert.match(html, /customer_id/);
assert.match(html, /c_001/);
"""
        )

    def test_project_archived_dataset_is_read_only_not_restorable(self):
        self.run_app_script(
            r"""
state.currentProjectId = "proj_default";
state.dashboard = {
  project: { id: "proj_default", name: "Default" },
  summary: { datasets: 1, jobs: 0, runs: 0, models: 0, evaluations: 0, experimentResults: 0 },
  datasets: [
    {
      id: "ds_old_features",
      name: "old-features",
      description: "Archived but historically linked",
      type: "tabular",
      versionCount: 1,
      latestVersion: "v1",
      owner: "alice",
      team: "ml",
      domain: "crm",
      sourceSystem: "warehouse",
      visibility: "team",
      tags: ["old"],
      status: "archived",
      createdAt: "2026-07-06T00:00:00Z",
      updatedAt: "2026-07-06T00:00:00Z",
      projectLink: { id: "pdl_1", role: "train", versionPolicy: "latest", pinnedVersion: null },
    },
  ],
  jobs: [],
  runs: [],
  models: [],
  evaluations: [],
  experimentResults: [],
};
state.selected.dataset = "ds_old_features";
state.details["dataset:ds_old_features"] = {
  versions: [{ id: "dv_old_v1", datasetId: "ds_old_features", version: "v1", format: "csv", storageUri: "s3://datasets/old/v1/data.csv", rowCount: 2, checksumStatus: "verified", trainable: true, approvalStatus: "approved" }],
  lineage: [],
};

renderDatasetDetail();
const html = elementFor("#datasetDetail").innerHTML;
assert.match(html, /archived/);
assert.match(html, /仅用于历史查看/);
assert.match(html, /data-preview-dataset-version="v1"/);
assert.match(html, /data-unlink-project-dataset="ds_old_features"/);
assert.doesNotMatch(html, /data-use-dataset-version/);
assert.doesNotMatch(html, /data-archive-dataset/);
assert.doesNotMatch(html, /data-restore-dataset/);
assert.doesNotMatch(html, /恢复数据集/);
"""
        )

    def test_workspace_catalog_rows_open_dataset_metadata(self):
        self.run_app_script(
            r"""
state.currentProjectId = null;
state.dashboard = {
  summary: { datasets: 1, jobs: 0, runs: 0, models: 0, evaluations: 0, experimentResults: 0 },
  projects: [],
  datasets: [
    {
      id: "ds_catalog_features",
      name: "catalog-features",
      description: "Global catalog dataset",
      type: "tabular",
      versionCount: 1,
      latestVersion: "v1",
      owner: "alice",
      team: "ml",
      domain: "crm",
      sourceSystem: "warehouse",
      visibility: "team",
      tags: ["golden"],
      status: "active",
      createdAt: "2026-07-06T00:00:00Z",
      updatedAt: "2026-07-06T00:00:00Z",
    },
  ],
  jobs: [],
  runs: [],
  models: [],
  evaluations: [],
  experimentResults: [],
};
state.selected.dataset = "ds_catalog_features";
state.details["dataset:ds_catalog_features"] = {
  versions: [{ id: "dv_catalog_v1", datasetId: "ds_catalog_features", version: "v1", format: "csv", storageUri: "s3://datasets/catalog/v1/data.csv", rowCount: 2, checksumStatus: "verified", trainable: true, approvalStatus: "approved" }],
  lineage: [],
};

renderProjectCards();

assert.match(elementFor("#catalogDatasetsBody").innerHTML, /data-resource-type="dataset" data-resource-id="ds_catalog_features"/);
const detailHtml = elementFor("#catalogDatasetDetail").innerHTML;
assert.match(detailHtml, /catalog-features/);
assert.match(detailHtml, /Global catalog dataset/);
assert.match(detailHtml, /DatasetVersion v1/);
assert.match(detailHtml, /data-preview-dataset-version="v1"/);
assert.doesNotMatch(detailHtml, /data-use-dataset-version="ds_catalog_features@v1"/);
assert.match(detailHtml, /归档全局数据集/);
assert.match(detailHtml, /全局资产级逻辑删除/);
assert.doesNotMatch(detailHtml, /data-unlink-project-dataset/);
"""
        )

    def test_workspace_catalog_can_switch_to_archived_datasets(self):
        self.run_app_script(
            r"""
const requestedPaths = [];
global.fetch = async (url) => ({
  ok: true,
  json: async () => {
    requestedPaths.push(String(url));
    return [
      {
        id: "ds_archived_features",
        name: "archived-features",
        description: "Old shared features",
        type: "tabular",
        versionCount: 1,
        latestVersion: "v1",
        owner: "alice",
        team: "ml",
        domain: "",
        sourceSystem: "",
        visibility: "team",
        tags: [],
        status: "archived",
        createdAt: "2026-07-06T00:00:00Z",
        updatedAt: "2026-07-06T00:00:00Z",
      },
    ];
  },
  text: async () => "",
});
state.currentProjectId = null;
state.dashboard = {
  summary: { datasets: 0, jobs: 0, runs: 0, models: 0, evaluations: 0, experimentResults: 0 },
  projects: [],
  datasets: [],
  jobs: [],
  runs: [],
  models: [],
  evaluations: [],
  experimentResults: [],
};

await setCatalogStatus("archived");

assert.ok(requestedPaths.some((path) => /\/api\/v1\/datasets\?status=archived$/.test(path)));
assert.strictEqual(state.catalog.status, "archived");
assert.strictEqual(state.selected.dataset, "ds_archived_features");
assert.match(elementFor("#catalogDatasetsBody").innerHTML, /archived-features/);
assert.match(elementFor("#catalogDatasetDetail").innerHTML, /恢复数据集/);
assert.doesNotMatch(elementFor("#catalogDatasetDetail").innerHTML, /data-use-dataset-version/);
"""
        )

    def test_preview_scroll_target_uses_active_dataset_surface(self):
        self.run_app_script(
            r"""
state.currentProjectId = null;
assert.strictEqual(activeDatasetDetailSelector(), "#catalogDatasetDetail");
state.currentProjectId = "proj_default";
assert.strictEqual(activeDatasetDetailSelector(), "#datasetDetail");
"""
        )

    def test_preview_button_toggles_selected_preview(self):
        self.run_app_script(
            r"""
state.currentProjectId = "proj_default";
state.dashboard = {
  project: { id: "proj_default", name: "Default" },
  summary: { datasets: 1, jobs: 0, runs: 0, models: 0, evaluations: 0, experimentResults: 0 },
  datasets: [
    {
      id: "ds_toggle",
      name: "toggle",
      description: "Toggle preview",
      type: "tabular",
      versionCount: 1,
      latestVersion: "v1",
      owner: "alice",
      team: "ml",
      visibility: "team",
      tags: [],
      status: "active",
      createdAt: "2026-07-06T00:00:00Z",
      updatedAt: "2026-07-06T00:00:00Z",
      projectLink: { id: "pdl_1", role: "train", versionPolicy: "latest", pinnedVersion: null },
    },
  ],
  jobs: [],
  runs: [],
  models: [],
  evaluations: [],
  experimentResults: [],
};
state.selected.dataset = "ds_toggle";
state.details["dataset:ds_toggle"] = {
  versions: [{ id: "dv_toggle_v1", datasetId: "ds_toggle", version: "v1", format: "csv", storageUri: "s3://datasets/toggle/v1/data.csv", rowCount: 1, checksumStatus: "verified", trainable: true, approvalStatus: "approved" }],
  lineage: [],
  selectedPreview: "v1",
  preview: { "v1": { version: "v1", rows: [{ x: 1 }], schema: { columns: [{ name: "x", type: "float" }] }, profile: { rows: 1, columns: 1 }, storageUri: "s3://datasets/toggle/v1/data.csv" } },
};

await previewDatasetVersion("v1");

assert.strictEqual(state.details["dataset:ds_toggle"].selectedPreview, "");
assert.doesNotMatch(elementFor("#datasetDetail").innerHTML, /preview-panel/);
"""
        )

    def test_use_dataset_version_selects_compatible_training_template(self):
        self.run_app_script(
            r"""
state.currentProjectId = "proj_default";
state.dashboard = {
  project: { id: "proj_default", name: "Default" },
  summary: { datasets: 1, jobs: 0, runs: 0, models: 0, evaluations: 0, experimentResults: 0 },
  datasets: [
    {
      id: "ds_blobs",
      name: "blobs",
      description: "Training data",
      type: "tabular",
      versionCount: 1,
      latestVersion: "v1",
      owner: "alice",
      team: "ml",
      domain: "",
      sourceSystem: "",
      visibility: "team",
      tags: [],
      status: "active",
      createdAt: "2026-07-06T00:00:00Z",
      updatedAt: "2026-07-06T00:00:00Z",
    },
  ],
  templates: [
    { id: "pytorch-sequence-forecast", name: "Sequence", datasetTypes: ["time_series"], executorStatus: "available", paramSchema: {} },
    { id: "sklearn-kmeans", name: "KMeans", datasetTypes: ["tabular"], executorStatus: "available", paramSchema: {} },
  ],
  jobs: [],
  runs: [],
  models: [],
  evaluations: [],
  experimentResults: [],
};
state.trainingForm.versions = [
  { id: "dv_blobs_v1", datasetName: "blobs", datasetType: "tabular", datasetStatus: "active", version: "v1", ref: "ds_blobs@v1", trainable: true },
];

await useDatasetVersionForTraining("ds_blobs@v1");

assert.strictEqual(elementFor("#jobTemplate").value, "sklearn-kmeans");
assert.strictEqual(elementFor("#jobDataset").value, "ds_blobs@v1");
assert.match(elementFor("#jobDataset").innerHTML, /blobs@v1/);
"""
        )
