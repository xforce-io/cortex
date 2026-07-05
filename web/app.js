const state = {
  dashboard: null,
  selectedRun: null,
  activeView: "dashboard",
  selected: {
    dataset: null,
    job: null,
    run: null,
    model: null,
    evaluation: null,
  },
  details: {},
  trainingForm: {
    open: false,
    versions: [],
    loadingVersions: false,
    submitting: false,
    error: "",
  },
  registrationForm: {
    runId: null,
    open: false,
    submitting: false,
    error: "",
  },
  expandedTables: {
    datasets: false,
    jobs: false,
    runs: false,
    models: false,
    evaluations: false,
  },
  pollingJobs: new Set(),
};

const $ = (selector) => document.querySelector(selector);

const API_BASE = window.CORTEX_API_BASE || (window.location.protocol === "file:" ? "http://127.0.0.1:8768" : "");

function apiUrl(path) {
  if (/^https?:\/\//.test(path)) return path;
  return `${API_BASE}${path}`;
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(apiUrl(path), {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (error) {
    const target = API_BASE || window.location.origin || "local API";
    throw new Error(`Cannot reach Cortex API at ${target}. Open http://127.0.0.1:8768/ or start the local API service.`);
  }
  if (!response.ok) {
    const text = await response.text();
    try {
      throw new Error(JSON.parse(text).error || response.statusText);
    } catch (error) {
      if (error instanceof SyntaxError) throw new Error(text || response.statusText);
      throw error;
    }
  }
  return response.json();
}

function shortId(value) {
  if (!value) return "empty";
  return value.length > 18 ? `${value.slice(0, 8)}...${value.slice(-6)}` : value;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function pill(status) {
  const normalized = String(status || "unknown").toLowerCase();
  return `<span class="pill ${escapeHtml(normalized)}">${escapeHtml(status || "unknown")}</span>`;
}

function progressBar(percent, message = "") {
  const value = Math.max(0, Math.min(100, Number(percent || 0)));
  return `
    <div class="progress-wrap" aria-label="Progress ${value}%">
      <div class="progress-track"><div class="progress-fill" style="width: ${value}%"></div></div>
      <span>${value}%${message ? ` · ${escapeHtml(message)}` : ""}</span>
    </div>
  `;
}

function rowEmpty(colspan, label) {
  return `<tr><td colspan="${colspan}">${label}</td></tr>`;
}

function selectedClass(type, id) {
  return state.selected[type] === id ? " selected" : "";
}

function clickableRow(type, id) {
  return `class="selectable-row${selectedClass(type, id)}" data-resource-type="${type}" data-resource-id="${escapeHtml(id)}" tabindex="0"`;
}

function limitedRows(key, items, columns, renderRow, emptyLabel) {
  if (!items.length) return rowEmpty(columns, emptyLabel);
  const expanded = Boolean(state.expandedTables[key]);
  const visible = expanded ? items : items.slice(0, 5);
  const rows = visible.map(renderRow);
  if (items.length > 5) {
    rows.push(`
      <tr class="view-more-row">
        <td colspan="${columns}">
          <button class="link-button" data-toggle-list="${escapeHtml(key)}">
            <span>${expanded ? "Show less" : `View more (${items.length - 5})`}</span>
          </button>
        </td>
      </tr>
    `);
  }
  return rows.join("");
}

async function refresh() {
  setHealth("checking");
  try {
    await api("/healthz");
    state.dashboard = await api("/api/v1/dashboard");
    state.selectedRun = state.dashboard.runs[0] || null;
    render();
    setHealth("ok");
  } catch (error) {
    setHealth("bad");
    $("#lastUpdated").textContent = error.message;
  }
}

function setHealth(status) {
  const dot = $("#healthDot");
  dot.className = `status-dot ${status === "ok" ? "ok" : status === "bad" ? "bad" : ""}`;
  $("#healthText").textContent = status === "ok" ? "Healthy" : status === "bad" ? "Unavailable" : "Checking";
}

function render() {
  const { summary, datasets, jobs, runs, models } = state.dashboard;
  ensureSelections();
  $("#metricDatasets").textContent = summary.datasets;
  $("#metricJobs").textContent = summary.jobs;
  $("#metricRuns").textContent = summary.runs;
  $("#metricModels").textContent = summary.models;
  $("#metricTests").textContent = summary.evaluations;
  $("#lastUpdated").textContent = `Synced ${new Date().toLocaleTimeString()}`;
  $("#emptyState").classList.toggle("visible", summary.datasets === 0 && summary.jobs === 0 && summary.models === 0);

  $("#datasetCount").textContent = `${datasets.length} records`;
  $("#datasetsBody").innerHTML = limitedRows(
    "datasets",
    datasets,
    6,
    (dataset) =>
      `<tr ${clickableRow("dataset", dataset.id)}><td>${escapeHtml(dataset.name)}</td><td>${escapeHtml(dataset.type)}</td><td>${dataset.versionCount || 0}</td><td>${escapeHtml(dataset.latestVersion || "")}</td><td>${escapeHtml(dataset.owner)}</td><td>${pill(dataset.status)}</td></tr>`,
    "No datasets",
  );

  $("#jobCount").textContent = `${jobs.length} records`;
  $("#jobsBody").innerHTML = limitedRows(
    "jobs",
    jobs,
    5,
    (job) =>
      `<tr ${clickableRow("job", job.id)}><td class="mono">${shortId(job.id)}</td><td>${escapeHtml(job.templateId)}</td><td>${pill(job.status)}${progressBar(job.progressPercent, job.statusMessage)}</td><td class="mono">${shortId(job.mlflowRunId)}</td><td>${escapeHtml(job.owner)}</td></tr>`,
    "No jobs",
  );

  $("#runCount").textContent = `${runs.length} records`;
  $("#runsBody").innerHTML = limitedRows(
    "runs",
    runs,
    5,
    (run) => {
      const dataset = run.tags?.dataset_version || "empty";
      const inertia = run.metrics?.inertia ?? "";
      const rows = run.metrics?.rows ?? "";
      return `<tr ${clickableRow("run", run.id)}><td class="mono">${shortId(run.id)}</td><td>${pill(run.status)}</td><td>${escapeHtml(dataset)}</td><td>${escapeHtml(inertia)}</td><td>${escapeHtml(rows)}</td></tr>`;
    },
    "No runs",
  );

  $("#modelCount").textContent = `${models.length} records`;
  $("#modelsBody").innerHTML = limitedRows(
    "models",
    models,
    4,
    (model) =>
      `<tr ${clickableRow("model", model.name)}><td>${escapeHtml(model.name)}</td><td>${model.versions.length}</td><td>${escapeHtml(model.aliases.champion || "")}</td><td>${escapeHtml(model.aliases.challenger || "")}</td></tr>`,
    "No models",
  );

  const evaluations = state.dashboard.evaluations || [];
  $("#testCount").textContent = `${evaluations.length} records`;
  $("#testsBody").innerHTML = limitedRows(
    "evaluations",
    evaluations,
    6,
    (evaluation) =>
      `<tr ${clickableRow("evaluation", evaluation.id)}><td class="mono">${shortId(evaluation.id)}</td><td>${escapeHtml(evaluation.registeredModelName)}:${escapeHtml(evaluation.modelVersion)}</td><td>${escapeHtml(evaluation.trainDatasetRef)}</td><td>${escapeHtml(evaluation.testDatasetRef)}</td><td>${escapeHtml(evaluation.metrics.test_inertia)}</td><td>${pill(evaluation.status)}</td></tr>`,
    "No tests",
  );

  renderAllDetails();
  renderTrainingForm();
  renderLineage();
  renderChart(runs);
  applyView(state.activeView);
}

function ensureSelections() {
  const { datasets, jobs, runs, models, evaluations = [] } = state.dashboard;
  state.selected.dataset = datasets.some((item) => item.id === state.selected.dataset) ? state.selected.dataset : datasets[0]?.id || null;
  state.selected.job = jobs.some((item) => item.id === state.selected.job) ? state.selected.job : jobs[0]?.id || null;
  state.selected.run = runs.some((item) => item.id === state.selected.run) ? state.selected.run : runs[0]?.id || null;
  state.selected.model = models.some((item) => item.name === state.selected.model) ? state.selected.model : models[0]?.name || null;
  state.selected.evaluation = evaluations.some((item) => item.id === state.selected.evaluation) ? state.selected.evaluation : evaluations[0]?.id || null;
  state.selectedRun = runs.find((run) => run.id === state.selected.run) || runs[0] || null;
}

function renderLineage() {
  const run = state.selectedRun;
  const models = state.dashboard?.models || [];
  const datasetRef = run?.tags?.dataset_version || "empty";
  const linkedModel = models.find((model) => model.versions.some((version) => version.runId === run?.id));
  const alias = linkedModel
    ? Object.entries(linkedModel.aliases)
        .map(([name, version]) => `${name}:${version}`)
        .join(", ") || "versioned"
    : "empty";
  $("#lineageLabel").textContent = run ? shortId(run.id) : "No run selected";
  $("#lineageDataset").textContent = shortId(datasetRef);
  $("#lineageRun").textContent = shortId(run?.id);
  $("#lineageModel").textContent = linkedModel ? `${linkedModel.name} ${alias}` : "empty";
}

function renderChart(runs) {
  const canvas = $("#metricsCanvas");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#eef3f2";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#c9d5d5";
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i += 1) {
    const y = (height / 4) * i;
    ctx.beginPath();
    ctx.moveTo(24, y);
    ctx.lineTo(width - 16, y);
    ctx.stroke();
  }
  const points = runs.filter((run) => typeof run.metrics?.inertia === "number");
  if (!points.length) {
    ctx.fillStyle = "#667276";
    ctx.font = "13px system-ui";
    ctx.fillText("No run metrics", 24, 92);
    return;
  }
  const maxInertia = Math.max(...points.map((run) => run.metrics.inertia), 1);
  points.forEach((run, index) => {
    const x = 32 + index * Math.max(28, (width - 64) / Math.max(points.length, 1));
    const y = height - 24 - (run.metrics.inertia / maxInertia) * (height - 52);
    ctx.fillStyle = run.id === state.selectedRun?.id ? "#2563eb" : "#0f766e";
    ctx.beginPath();
    ctx.arc(Math.min(x, width - 24), y, 6, 0, Math.PI * 2);
    ctx.fill();
  });
}

function findResource(type, id) {
  const data = state.dashboard;
  if (!data) return null;
  if (type === "dataset") return data.datasets.find((item) => item.id === id);
  if (type === "job") return data.jobs.find((item) => item.id === id);
  if (type === "run") return data.runs.find((item) => item.id === id);
  if (type === "model") return data.models.find((item) => item.name === id);
  if (type === "evaluation") return (data.evaluations || []).find((item) => item.id === id);
  return null;
}

function detailKey(type, id) {
  return `${type}:${id}`;
}

function detailList(items) {
  return `<dl class="detail-grid">${items.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${value || "empty"}</dd></div>`).join("")}</dl>`;
}

function jsonBlock(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2);
  return `<pre class="detail-json">${escapeHtml(text || "empty")}</pre>`;
}

function renderCollection(items, emptyLabel = "empty") {
  if (!items?.length) return `<p class="muted">${escapeHtml(emptyLabel)}</p>`;
  return `<ul class="detail-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function modelVersionForRun(runId) {
  const models = state.dashboard?.models || [];
  for (const model of models) {
    const version = model.versions.find((item) => item.runId === runId);
    if (version) return { model, version };
  }
  return null;
}

function canRegisterRun(run) {
  return run?.status === "FINISHED" && (run.artifacts || []).includes("model/model.json") && !modelVersionForRun(run.id);
}

function defaultModelName(run) {
  const dataset = String(run?.tags?.dataset_version || "model").split("@")[0] || "model";
  return `${dataset.replace(/^ds_/, "").replace(/_/g, "-")}-kmeans`;
}

function renderRegistrationForm(run) {
  if (!state.registrationForm.open || state.registrationForm.runId !== run.id) return "";
  return `
    <section class="inline-form compact-form">
      <form data-register-model-form="${escapeHtml(run.id)}">
        <div class="form-grid">
          <label>
            <span>Model name</span>
            <input name="modelName" value="${escapeHtml(defaultModelName(run))}" required />
          </label>
          <label>
            <span>Alias</span>
            <select name="alias">
              <option value="">No alias</option>
              <option value="challenger">challenger</option>
              <option value="champion">champion</option>
            </select>
          </label>
          <label>
            <span>Description</span>
            <input name="description" value="${escapeHtml(`Registered from ${shortId(run.id)}`)}" />
          </label>
        </div>
        <div class="form-footer">
          <p class="${state.registrationForm.error ? "form-error" : ""}">${escapeHtml(state.registrationForm.error)}</p>
          <div class="toolbar">
            <button class="secondary-button" type="button" data-cancel-register>Cancel</button>
            <button class="primary-button" type="submit" ${state.registrationForm.submitting ? "disabled" : ""}>Register model version</button>
          </div>
        </div>
      </form>
    </section>
  `;
}

function currentTemplate() {
  const templates = executableTemplates();
  const selected = $("#jobTemplate")?.value;
  return templates.find((template) => template.id === selected) || templates[0] || null;
}

function executableTemplates() {
  return (state.dashboard?.templates || []).filter((template) => template.executorStatus === "available" || (template.executorStatus == null && template.id === "sklearn-kmeans"));
}

function renderTrainingForm() {
  const panel = $("#trainingJobForm");
  if (!panel) return;
  panel.hidden = !state.trainingForm.open;
  renderTemplateOptions();
  renderDatasetOptions();
  renderParamInputs();
  renderJobFormStatus();
}

function renderTemplateOptions() {
  const select = $("#jobTemplate");
  if (!select || !state.dashboard) return;
  const current = select.value;
  const templates = executableTemplates();
  select.innerHTML = templates.map((template) => `<option value="${escapeHtml(template.id)}">${escapeHtml(template.name)} · ${escapeHtml(template.id)}</option>`).join("");
  select.disabled = !templates.length;
  if (templates.some((template) => template.id === current)) select.value = current;
}

function compatibleVersions(template) {
  const datasetTypes = template?.datasetTypes || [];
  return state.trainingForm.versions.filter((item) => item.trainable && (!datasetTypes.length || datasetTypes.includes(item.datasetType)));
}

function renderDatasetOptions() {
  const select = $("#jobDataset");
  if (!select) return;
  const selected = select.value;
  const template = currentTemplate();
  const versions = compatibleVersions(template);
  if (state.trainingForm.loadingVersions) {
    select.innerHTML = `<option value="">Loading dataset versions</option>`;
    select.disabled = true;
    return;
  }
  select.disabled = !versions.length;
  select.innerHTML = versions.length
    ? versions.map((item) => `<option value="${escapeHtml(item.ref)}">${escapeHtml(item.datasetName)}@${escapeHtml(item.version)} · ${escapeHtml(item.datasetType)}</option>`).join("")
    : `<option value="">No compatible dataset versions</option>`;
  if (versions.some((item) => item.ref === selected)) select.value = selected;
}

function renderParamInputs() {
  const container = $("#jobParams");
  const template = currentTemplate();
  if (!container || !template) {
    if (container) container.innerHTML = "";
    return;
  }
  const schema = template.paramSchema || {};
  container.innerHTML = Object.entries(schema)
    .map(([name, type]) => {
      const inputType = type === "int" || type === "float" ? "number" : "text";
      const step = type === "float" ? "any" : "1";
      const value = name === "n_clusters" ? "3" : name === "random_state" ? "42" : name === "target" ? "price" : "";
      return `<label><span>${escapeHtml(name)}</span><input name="param:${escapeHtml(name)}" type="${inputType}" step="${step}" value="${escapeHtml(value)}" /></label>`;
    })
    .join("");
}

function renderJobFormStatus() {
  const status = $("#jobFormStatus");
  if (!status) return;
  if (!state.dashboard) {
    status.textContent = "Connect to the local Cortex API, then refresh data";
    status.className = "form-error";
  } else if (!executableTemplates().length) {
    status.textContent = "No executable templates in this API response. Refresh the page or restart the local service.";
    status.className = "form-error";
  } else if (state.trainingForm.error) {
    status.textContent = state.trainingForm.error;
    status.className = "form-error";
  } else if (state.trainingForm.submitting) {
    status.textContent = "Submitting job";
    status.className = "";
  } else {
    status.textContent = "";
    status.className = "";
  }
  const submit = $("#submitJobButton");
  if (submit) submit.disabled = !executableTemplates().length || state.trainingForm.submitting || state.trainingForm.loadingVersions || !$("#jobDataset")?.value;
}

function setDetail(containerId, title, subtitle, body) {
  $(containerId).innerHTML = `
    <div class="detail-header">
      <div>
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(subtitle)}</p>
      </div>
    </div>
    ${body}
  `;
}

function renderAllDetails() {
  renderDatasetDetail();
  renderJobDetail();
  renderRunDetail();
  renderModelDetail();
  renderEvaluationDetail();
}

function renderDatasetDetail() {
  const dataset = findResource("dataset", state.selected.dataset);
  if (!dataset) {
    setDetail("#datasetDetail", "Dataset detail", "Select a dataset", "");
    return;
  }
  const extra = state.details[detailKey("dataset", dataset.id)];
  const versions = extra?.versions || [];
  const lineage = extra?.lineage || [];
  setDetail(
    "#datasetDetail",
    dataset.name,
    dataset.description || dataset.id,
    detailList([
      ["ID", `<span class="mono">${escapeHtml(dataset.id)}</span>`],
      ["Type", escapeHtml(dataset.type)],
      ["Owner", escapeHtml(dataset.owner)],
      ["Team", escapeHtml(dataset.team)],
      ["Visibility", escapeHtml(dataset.visibility)],
      ["Tags", escapeHtml((dataset.tags || []).join(", ") || "empty")],
      ["Created", escapeHtml(dataset.createdAt)],
      ["Updated", escapeHtml(dataset.updatedAt)],
    ]) +
      `<h4>Versions</h4>${versions.length ? detailList(versions.map((version) => [`${version.version} · ${version.format}`, `${escapeHtml(version.storageUri)} · rows ${escapeHtml(version.rowCount ?? "unknown")} · ${escapeHtml(version.checksumStatus)}`])) : `<p class="muted">${extra ? "No versions" : "Loading versions"}</p>`}` +
      `<h4>Lineage</h4>${lineage.length ? detailList(lineage.map((item) => [shortId(item.mlflowRunId), `${escapeHtml(item.jobStatus)} · ${escapeHtml(item.registeredModelName || "no model")}${item.modelVersion ? `:${escapeHtml(item.modelVersion)}` : ""}`])) : `<p class="muted">${extra ? "No downstream runs" : "Loading lineage"}</p>`}`,
  );
}

function renderJobDetail() {
  const job = findResource("job", state.selected.job);
  if (!job) {
    setDetail("#jobDetail", "Job detail", "Select a training job", "");
    return;
  }
  const extra = state.details[detailKey("job", job.id)];
  const registered = modelVersionForRun(job.mlflowRunId);
  const jobRun = findResource("run", job.mlflowRunId);
  const registerAction = canRegisterRun(jobRun)
    ? `<button class="link-button" data-register-run="${escapeHtml(job.mlflowRunId)}"><span>Register as model</span></button>`
    : "";
  setDetail(
    "#jobDetail",
    shortId(job.id),
    job.experimentName,
    detailList([
      ["ID", `<span class="mono">${escapeHtml(job.id)}</span>`],
      ["Template", escapeHtml(job.templateId)],
      ["Status", pill(job.status)],
      ["Progress", progressBar(job.progressPercent, job.statusMessage)],
      ["Dataset Version ID", `<span class="mono">${escapeHtml(job.datasetVersionId)}</span>`],
      [
        "Run",
        job.mlflowRunId
          ? `<div class="inline-actions"><button class="link-button" data-jump-run="${escapeHtml(job.mlflowRunId)}"><span class="mono">${escapeHtml(job.mlflowRunId)}</span><span>View training results</span></button>${registerAction}</div>`
          : "empty",
      ],
      ["Model Registry", registered ? `${escapeHtml(registered.model.name)}:${escapeHtml(registered.version.version)}` : "Not registered"],
      ["Owner", escapeHtml(job.owner)],
      ["Created", escapeHtml(job.createdAt)],
      ["Started", escapeHtml(job.startedAt)],
      ["Finished", escapeHtml(job.finishedAt)],
      ["Error", escapeHtml(job.errorMessage)],
    ]) +
      `<h4>Params</h4>${jsonBlock(job.params)}` +
      `<h4>Logs</h4>${jsonBlock(extra?.logs ?? (extra ? "" : "Loading logs"))}`,
  );
}

function renderRunDetail() {
  const run = findResource("run", state.selected.run);
  if (!run) {
    setDetail("#runDetail", "Run detail", "Select an experiment run", "");
    return;
  }
  const registered = modelVersionForRun(run.id);
  const registryValue = registered
    ? `${escapeHtml(registered.model.name)}:${escapeHtml(registered.version.version)}`
    : canRegisterRun(run)
      ? `<button class="secondary-button" data-open-register-run="${escapeHtml(run.id)}">Register as model</button>`
      : "Not registerable";
  setDetail(
    "#runDetail",
    shortId(run.id),
    run.experimentName,
    detailList([
      ["ID", `<span class="mono">${escapeHtml(run.id)}</span>`],
      ["Status", pill(run.status)],
      ["Experiment", escapeHtml(run.experimentName)],
      ["Job", `<span class="mono">${escapeHtml(run.platform?.jobId || "empty")}</span>`],
      ["Dataset", escapeHtml(run.tags?.dataset_version || "")],
      ["Model Registry", registryValue],
      ["Created", escapeHtml(run.createdAt)],
      ["Ended", escapeHtml(run.endedAt)],
    ]) +
      renderRegistrationForm(run) +
      `<h4>Metrics</h4>${jsonBlock(run.metrics)}` +
      `<h4>Params</h4>${jsonBlock(run.params)}` +
      `<h4>Tags</h4>${jsonBlock(run.tags)}` +
      `<h4>Inputs</h4>${jsonBlock(run.inputs)}` +
      `<h4>Artifacts</h4>${renderCollection(run.artifacts, "No artifacts")}`,
  );
}

function renderModelDetail() {
  const model = findResource("model", state.selected.model);
  if (!model) {
    setDetail("#modelDetail", "Model detail", "Select a model", "");
    return;
  }
  setDetail(
    "#modelDetail",
    model.name,
    `${model.versions.length} versions`,
    detailList([
      ["Name", escapeHtml(model.name)],
      ["Champion", escapeHtml(model.aliases.champion || "empty")],
      ["Challenger", escapeHtml(model.aliases.challenger || "empty")],
      ["Created", escapeHtml(model.createdAt)],
    ]) +
      `<h4>Versions</h4>${model.versions.length ? detailList(model.versions.map((version) => [`Version ${version.version}`, `run ${escapeHtml(shortId(version.runId))} · ${escapeHtml(version.artifactPath)} · ${escapeHtml(version.description || "no description")}`])) : `<p class="muted">No versions</p>`}`,
  );
}

function renderEvaluationDetail() {
  const evaluation = findResource("evaluation", state.selected.evaluation);
  if (!evaluation) {
    setDetail("#evaluationDetail", "Evaluation detail", "Select an evaluation", "");
    return;
  }
  setDetail(
    "#evaluationDetail",
    shortId(evaluation.id),
    `${evaluation.registeredModelName}:${evaluation.modelVersion}`,
    detailList([
      ["ID", `<span class="mono">${escapeHtml(evaluation.id)}</span>`],
      ["Model", `${escapeHtml(evaluation.registeredModelName)}:${escapeHtml(evaluation.modelVersion)}`],
      ["Status", pill(evaluation.status)],
      ["Run", `<span class="mono">${escapeHtml(evaluation.runId)}</span>`],
      ["Train Dataset", escapeHtml(evaluation.trainDatasetRef)],
      ["Test Dataset", escapeHtml(evaluation.testDatasetRef)],
      ["Owner", escapeHtml(evaluation.owner)],
      ["Created", escapeHtml(evaluation.createdAt)],
    ]) + `<h4>Metrics</h4>${jsonBlock(evaluation.metrics)}`,
  );
}

async function selectResource(type, id) {
  if (!id || !state.dashboard) return;
  state.selected[type] = id;
  if (type === "run") {
    state.selectedRun = findResource("run", id) || state.selectedRun;
    renderLineage();
    renderChart(state.dashboard.runs);
  }
  render();
  await loadResourceDetail(type, id);
}

async function jumpToRun(runId) {
  if (!runId || !state.dashboard) return;
  state.selected.run = runId;
  state.selectedRun = findResource("run", runId) || state.selectedRun;
  applyView("runs");
  render();
  await loadResourceDetail("run", runId);
}

function openRegistrationForm(runId) {
  const run = findResource("run", runId);
  if (!canRegisterRun(run)) return;
  state.registrationForm = {
    runId,
    open: true,
    submitting: false,
    error: "",
  };
  state.selected.run = runId;
  state.selectedRun = run;
  applyView("runs");
  render();
}

function closeRegistrationForm() {
  state.registrationForm.open = false;
  state.registrationForm.error = "";
  renderRunDetail();
}

async function submitModelRegistration(event) {
  const form = event.target.closest("[data-register-model-form]");
  if (!form) return;
  event.preventDefault();
  const runId = form.dataset.registerModelForm;
  const run = findResource("run", runId);
  if (!run) return;
  const data = new FormData(form);
  const modelName = String(data.get("modelName") || "").trim();
  const alias = String(data.get("alias") || "");
  state.registrationForm.submitting = true;
  state.registrationForm.error = "";
  renderRunDetail();
  try {
    const version = await api(`/api/v1/models/${encodeURIComponent(modelName)}/versions`, {
      method: "POST",
      body: JSON.stringify({
        runId,
        artifactPath: "model",
        description: data.get("description") || "",
        tags: {
          dataset_version: run.tags?.dataset_version || "",
          source_job: run.platform?.jobId || "",
        },
      }),
    });
    if (alias) {
      await api(`/api/v1/models/${encodeURIComponent(modelName)}/aliases/${encodeURIComponent(alias)}`, {
        method: "POST",
        body: JSON.stringify({
          version: version.version,
          operator: run.tags?.owner || "unknown",
          reason: `Registered from ${runId}`,
        }),
      });
    }
    state.registrationForm.open = false;
    state.selected.model = modelName;
    await refresh();
    state.selected.run = runId;
    state.selectedRun = findResource("run", runId) || run;
    applyView("runs");
    render();
  } catch (error) {
    state.registrationForm.error = error.message;
  } finally {
    state.registrationForm.submitting = false;
    renderRunDetail();
  }
}

async function openTrainingForm() {
  state.trainingForm.open = true;
  state.trainingForm.error = "";
  renderTrainingForm();
  await loadTrainingVersions();
}

function closeTrainingForm() {
  state.trainingForm.open = false;
  state.trainingForm.error = "";
  renderTrainingForm();
}

async function loadTrainingVersions() {
  if (state.trainingForm.loadingVersions || state.trainingForm.versions.length || !state.dashboard) return;
  state.trainingForm.loadingVersions = true;
  renderTrainingForm();
  try {
    const grouped = await Promise.all(
      state.dashboard.datasets.map(async (dataset) => {
        const versions = await api(`/api/v1/datasets/${encodeURIComponent(dataset.id)}/versions`);
        return versions.map((version) => ({
          ...version,
          datasetName: dataset.name,
          datasetType: dataset.type,
          ref: `${dataset.id}@${version.version}`,
        }));
      }),
    );
    state.trainingForm.versions = grouped.flat();
  } catch (error) {
    state.trainingForm.error = error.message;
  } finally {
    state.trainingForm.loadingVersions = false;
    renderTrainingForm();
  }
}

function coerceParam(value, type) {
  if (value === "") return undefined;
  if (type === "int") return Number.parseInt(value, 10);
  if (type === "float") return Number.parseFloat(value);
  return value;
}

async function submitTrainingJob(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const template = currentTemplate();
  const data = new FormData(form);
  if (!template) return;
  const params = {};
  Object.entries(template.paramSchema || {}).forEach(([name, type]) => {
    const value = coerceParam(data.get(`param:${name}`), type);
    if (value !== undefined && !Number.isNaN(value)) params[name] = value;
  });
  state.trainingForm.submitting = true;
  state.trainingForm.error = "";
  renderJobFormStatus();
  try {
    const job = await api("/api/v1/training/jobs", {
      method: "POST",
      body: JSON.stringify({
        templateId: data.get("templateId"),
        datasetRef: data.get("datasetRef"),
        experimentName: data.get("experimentName"),
        owner: data.get("owner"),
        team: data.get("team"),
        params,
      }),
    });
    state.selected.job = job.id;
    state.trainingForm.open = false;
    upsertJob(job);
    render();
    applyView("training");
    await loadResourceDetail("job", job.id);
    pollJob(job.id);
  } catch (error) {
    state.trainingForm.error = error.message;
  } finally {
    state.trainingForm.submitting = false;
    renderTrainingForm();
  }
}

function upsertJob(job) {
  const jobs = state.dashboard?.jobs || [];
  const index = jobs.findIndex((item) => item.id === job.id);
  if (index >= 0) {
    jobs[index] = job;
  } else {
    jobs.unshift(job);
    if (state.dashboard?.summary) state.dashboard.summary.jobs += 1;
  }
}

async function pollJob(jobId, attempts = 0) {
  if (!jobId || state.pollingJobs.has(jobId)) return;
  state.pollingJobs.add(jobId);
  try {
    let current = findResource("job", jobId);
    while (attempts < 20 && current && !["succeeded", "failed", "canceled"].includes(current.status)) {
      await new Promise((resolve) => setTimeout(resolve, 700));
      await refresh();
      current = findResource("job", jobId);
      attempts += 1;
    }
    if (current) {
      delete state.details[detailKey("job", jobId)];
      await loadResourceDetail("job", jobId);
    }
  } finally {
    state.pollingJobs.delete(jobId);
  }
}

async function loadResourceDetail(type, id) {
  const key = detailKey(type, id);
  if (state.details[key]) return;
  try {
    if (type === "dataset") {
      const dataset = findResource("dataset", id);
      const versions = await api(`/api/v1/datasets/${encodeURIComponent(id)}/versions`);
      const latest = dataset?.latestVersion;
      const lineage = latest ? await api(`/api/v1/datasets/${encodeURIComponent(id)}/versions/${encodeURIComponent(latest)}/runs`) : [];
      state.details[key] = { versions, lineage };
    } else if (type === "job") {
      const logs = await api(`/api/v1/training/jobs/${encodeURIComponent(id)}/logs`);
      state.details[key] = logs;
    } else {
      state.details[key] = {};
    }
  } catch (error) {
    state.details[key] = { error: error.message };
  }
  renderAllDetails();
}

async function runFullTest() {
  const button = $("#fullTestButton");
  const emptyButton = $("#emptyImportButton");
  if (button) button.disabled = true;
  emptyButton.disabled = true;
  if (button) button.textContent = "Creating example workspace";
  emptyButton.textContent = "Creating example workspace";
  try {
    await api("/api/v1/demo/full-test", { method: "POST", body: "{}" });
    await refresh();
  } finally {
    if (button) button.disabled = false;
    emptyButton.disabled = false;
    if (button) button.textContent = "Create example workspace";
    emptyButton.textContent = "Create example workspace";
  }
}

function applyView(view) {
  state.activeView = view;
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  document.querySelectorAll(".dashboard-view").forEach((section) => section.classList.toggle("active", section.id === view));
  document.querySelectorAll(".table-view").forEach((section) => section.classList.toggle("active", section.id === view));
  const titles = {
    dashboard: "Dashboard",
    datasets: "Datasets",
    training: "Training Jobs",
    runs: "Experiments",
    models: "Models",
    tests: "Evaluations",
  };
  document.querySelector("h1").textContent = titles[view] || "Workspace";
  const selectedByView = {
    datasets: ["dataset", state.selected.dataset],
    training: ["job", state.selected.job],
    runs: ["run", state.selected.run],
    models: ["model", state.selected.model],
    tests: ["evaluation", state.selected.evaluation],
  };
  const selection = selectedByView[view];
  if (selection) loadResourceDetail(selection[0], selection[1]);
}

function bindNav() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => {
      applyView(item.dataset.view);
    });
  });
}

document.addEventListener("click", (event) => {
  const listToggle = event.target.closest("[data-toggle-list]");
  if (listToggle) {
    event.preventDefault();
    const key = listToggle.dataset.toggleList;
    state.expandedTables[key] = !state.expandedTables[key];
    render();
    return;
  }
  const metricLink = event.target.closest("[data-view-target]");
  if (metricLink) {
    event.preventDefault();
    applyView(metricLink.dataset.viewTarget);
    return;
  }
  const openRegisterButton = event.target.closest("[data-open-register-run]");
  if (openRegisterButton) {
    event.preventDefault();
    openRegistrationForm(openRegisterButton.dataset.openRegisterRun);
    return;
  }
  const registerButton = event.target.closest("[data-register-run]");
  if (registerButton) {
    event.preventDefault();
    openRegistrationForm(registerButton.dataset.registerRun);
    return;
  }
  if (event.target.closest("[data-cancel-register]")) {
    event.preventDefault();
    closeRegistrationForm();
    return;
  }
  const runButton = event.target.closest("[data-jump-run]");
  if (runButton) {
    event.preventDefault();
    jumpToRun(runButton.dataset.jumpRun);
    return;
  }
  const row = event.target.closest("tr[data-resource-type]");
  if (!row || !state.dashboard) return;
  selectResource(row.dataset.resourceType, row.dataset.resourceId);
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const runButton = event.target.closest("[data-jump-run]");
  if (runButton) {
    event.preventDefault();
    jumpToRun(runButton.dataset.jumpRun);
    return;
  }
  const row = event.target.closest("tr[data-resource-type]");
  if (!row || !state.dashboard) return;
  event.preventDefault();
  selectResource(row.dataset.resourceType, row.dataset.resourceId);
});

document.addEventListener("submit", submitModelRegistration);

$("#refreshButton").addEventListener("click", refresh);
$("#fullTestButton")?.addEventListener("click", runFullTest);
$("#emptyImportButton").addEventListener("click", runFullTest);
$("#newJobButton").addEventListener("click", openTrainingForm);
$("#cancelJobForm").addEventListener("click", closeTrainingForm);
$("#jobTemplate").addEventListener("change", () => {
  renderDatasetOptions();
  renderParamInputs();
  renderJobFormStatus();
});
$("#jobForm").addEventListener("submit", submitTrainingJob);
bindNav();
refresh();
