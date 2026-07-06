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
global.document = {
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
