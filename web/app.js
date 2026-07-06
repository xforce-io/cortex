const state = {
  locale: "zh-CN",
  dashboard: null,
  projects: [],
  currentProjectId: null,
  selectedRun: null,
  activeView: "dashboard",
  selected: {
    dataset: null,
    job: null,
    run: null,
    model: null,
    result: null,
    evaluation: null,
  },
  details: {},
  datasetVersionTargets: {},
  trainingForm: {
    open: false,
    versions: [],
    loadingVersions: false,
    submitting: false,
    error: "",
    sourceJobId: null,
    defaults: {},
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
    results: false,
    evaluations: false,
  },
  pollingJobs: new Set(),
};

const $ = (selector) => document.querySelector(selector);

const API_BASE = window.CORTEX_API_BASE || (window.location.protocol === "file:" ? "http://127.0.0.1:8768" : "");
const DEFAULT_LOCALE = "zh-CN";
const LOCALE_STORAGE_KEY = "cortex.locale";
const I18N = {
  "zh-CN": {
    "action.cancel": "取消",
    "action.archiveDataset": "归档数据集",
    "action.createExample": "创建示例工作区",
    "action.creatingExample": "正在创建示例工作区",
    "action.editMetadata": "保存元数据",
    "action.newTrainingJob": "新建训练任务",
    "action.preview": "预览",
    "action.refresh": "刷新",
    "action.refreshData": "刷新数据",
    "action.registerAsModel": "注册为模型",
    "action.removeFromProject": "从项目移除",
    "action.restoreDataset": "恢复数据集",
    "action.registerModelVersion": "注册模型版本",
    "action.submitJob": "提交任务",
    "action.useForTraining": "用于训练",
    "action.viewTrainingResults": "查看训练结果",
    "aria.lineage": "数据集到任务、运行、模型的血缘",
    "aria.primary": "主导航",
    "aria.progress": "进度 {value}%",
    "aria.runMetrics": "运行指标图表",
    "aria.summary": "摘要",
    "brand.subtitle": "机器学习平台",
    "common.empty": "空",
    "common.loadingLineage": "正在加载血缘",
    "common.loadingLogs": "正在加载日志",
    "common.loadingVersions": "正在加载版本",
    "common.noArtifacts": "没有制品",
    "common.noDescription": "无描述",
    "common.noDownstreamRuns": "没有下游运行",
    "common.noModel": "无模型",
    "common.noProjects": "没有项目",
    "common.noRunMetrics": "没有运行指标",
    "common.noRunSelected": "未选择运行",
    "common.noVersions": "没有版本",
    "common.notRegistered": "未注册",
    "common.notRegisterable": "不可注册",
    "common.records": "{count} 条记录",
    "common.showLess": "收起",
    "common.unknown": "未知",
    "common.versioned": "已版本化",
    "common.viewMore": "查看更多 ({count})",
    "empty.copy": "创建一个示例项目，在同一工作区查看数据集版本、训练运行、模型注册和评估结果。",
    "empty.title": "还没有机器学习资产",
    "error.apiReach": "无法访问 Cortex API：{target}。请打开 http://127.0.0.1:8768/ 或启动本地 API 服务。",
    "field.artifact": "制品",
    "field.challenger": "Challenger",
    "field.champion": "Champion",
    "field.created": "创建时间",
    "field.createdBy": "创建人",
    "field.dataset": "数据集",
    "field.datasetCatalog": "数据集目录",
    "field.datasetVersion": "数据集版本",
    "field.datasetVersionId": "数据集版本 ID",
    "field.description": "描述",
    "field.domain": "领域",
    "field.ended": "结束时间",
    "field.error": "错误",
    "field.evaluation": "评估",
    "field.experiment": "实验",
    "field.finished": "完成时间",
    "field.id": "ID",
    "field.job": "任务",
    "field.kind": "类别",
    "field.latest": "最新",
    "field.method": "方法",
    "field.model": "模型",
    "field.modelName": "模型名称",
    "field.modelRegistry": "模型注册表",
    "field.name": "名称",
    "field.owner": "负责人",
    "field.progress": "进度",
    "field.project": "项目",
    "field.rank": "排名",
    "field.rows": "行数",
    "field.run": "运行",
    "field.source": "来源",
    "field.started": "开始时间",
    "field.status": "状态",
    "field.tags": "标签",
    "field.team": "团队",
    "field.template": "模板",
    "field.testDataset": "测试数据集",
    "field.testInertia": "测试 Inertia",
    "field.testSet": "测试集",
    "field.trainDataset": "训练数据集",
    "field.type": "类型",
    "field.updated": "更新时间",
    "field.versions": "版本",
    "field.visibility": "可见性",
    "form.connectApi": "连接本地 Cortex API，然后刷新数据",
    "form.editingFailedJob": "正在编辑失败任务 {id}。提交会创建新任务。",
    "form.loadingDatasetVersions": "正在加载数据集版本",
    "form.noAlias": "不设置别名",
    "form.noCompatibleDatasetVersions": "没有兼容的数据集版本",
    "form.noExecutableTemplates": "这个 API 响应里没有可执行模板。请刷新页面或重启本地服务。",
    "form.registeredFrom": "注册自 {id}",
    "form.submittingJob": "正在提交任务",
    "health.checking": "检查中",
    "health.healthy": "健康",
    "health.unavailable": "不可用",
    "label.alias": "别名",
    "lineage.jobRun": "任务 / 运行",
    "lineage.modelAlias": "模型别名",
    "locale.label": "语言",
    "metric.datasets": "数据集",
    "metric.datasetsSingular": "数据集",
    "metric.jobs": "任务",
    "metric.models": "模型",
    "metric.results": "结果",
    "metric.runs": "运行",
    "metric.tests": "测试",
    "nav.dashboard": "仪表盘",
    "nav.datasets": "数据集",
    "nav.models": "模型",
    "nav.results": "结果",
    "nav.runs": "实验",
    "nav.tests": "评估",
    "nav.training": "训练",
    "page.datasetDetail": "数据集详情",
    "page.evaluationDetail": "评估详情",
    "page.jobDetail": "任务详情",
    "page.modelDetail": "模型详情",
    "page.projects": "项目",
    "page.resultDetail": "结果详情",
    "page.runDetail": "运行详情",
    "page.trainingJobs": "训练任务",
    "page.workspace": "工作区",
    "section.artifacts": "制品",
    "section.inputs": "输入",
    "section.lineage": "血缘",
    "section.logs": "日志",
    "section.metadata": "元数据",
    "section.metrics": "指标",
    "section.preview": "预览",
    "section.projectLink": "项目引用",
    "section.params": "参数",
    "section.runMetrics": "运行指标",
    "section.tags": "标签",
    "section.versions": "版本",
    "select.dataset": "选择一个数据集",
    "select.evaluation": "选择一个评估",
    "select.model": "选择一个模型",
    "select.result": "选择一个结果",
    "select.run": "选择一个实验运行",
    "select.trainingJob": "选择一个训练任务",
    "table.noDatasets": "没有数据集",
    "table.noEvaluations": "没有评估",
    "table.noJobs": "没有任务",
    "table.noModels": "没有模型",
    "table.noResults": "没有结果",
    "table.noRuns": "没有运行",
  },
  en: {
    "action.cancel": "Cancel",
    "action.archiveDataset": "Archive dataset",
    "action.createExample": "Create example workspace",
    "action.creatingExample": "Creating example workspace",
    "action.editMetadata": "Save metadata",
    "action.newTrainingJob": "New training job",
    "action.preview": "Preview",
    "action.refresh": "Refresh",
    "action.refreshData": "Refresh data",
    "action.registerAsModel": "Register as model",
    "action.removeFromProject": "Remove from project",
    "action.restoreDataset": "Restore dataset",
    "action.registerModelVersion": "Register model version",
    "action.submitJob": "Submit job",
    "action.useForTraining": "Use for training",
    "action.viewTrainingResults": "View training results",
    "aria.lineage": "Dataset to job to run to model lineage",
    "aria.primary": "Primary",
    "aria.progress": "Progress {value}%",
    "aria.runMetrics": "Run metrics chart",
    "aria.summary": "Summary",
    "brand.subtitle": "ML Platform",
    "common.empty": "empty",
    "common.loadingLineage": "Loading lineage",
    "common.loadingLogs": "Loading logs",
    "common.loadingVersions": "Loading versions",
    "common.noArtifacts": "No artifacts",
    "common.noDescription": "no description",
    "common.noDownstreamRuns": "No downstream runs",
    "common.noModel": "no model",
    "common.noProjects": "No projects",
    "common.noRunMetrics": "No run metrics",
    "common.noRunSelected": "No run selected",
    "common.noVersions": "No versions",
    "common.notRegistered": "Not registered",
    "common.notRegisterable": "Not registerable",
    "common.records": "{count} records",
    "common.showLess": "Show less",
    "common.unknown": "unknown",
    "common.versioned": "versioned",
    "common.viewMore": "View more ({count})",
    "empty.copy": "Create a sample project to review dataset versioning, training runs, model registration, and evaluation results in one workspace.",
    "empty.title": "No ML assets yet",
    "error.apiReach": "Cannot reach Cortex API at {target}. Open http://127.0.0.1:8768/ or start the local API service.",
    "field.artifact": "Artifact",
    "field.challenger": "Challenger",
    "field.champion": "Champion",
    "field.created": "Created",
    "field.createdBy": "Created By",
    "field.dataset": "Dataset",
    "field.datasetCatalog": "Dataset Catalog",
    "field.datasetVersion": "Dataset version",
    "field.datasetVersionId": "Dataset Version ID",
    "field.description": "Description",
    "field.domain": "Domain",
    "field.ended": "Ended",
    "field.error": "Error",
    "field.evaluation": "Evaluation",
    "field.experiment": "Experiment",
    "field.finished": "Finished",
    "field.id": "ID",
    "field.job": "Job",
    "field.kind": "Kind",
    "field.latest": "Latest",
    "field.method": "Method",
    "field.model": "Model",
    "field.modelName": "Model name",
    "field.modelRegistry": "Model Registry",
    "field.name": "Name",
    "field.owner": "Owner",
    "field.progress": "Progress",
    "field.project": "Project",
    "field.rank": "Rank",
    "field.rows": "Rows",
    "field.run": "Run",
    "field.source": "Source",
    "field.started": "Started",
    "field.status": "Status",
    "field.tags": "Tags",
    "field.team": "Team",
    "field.template": "Template",
    "field.testDataset": "Test Dataset",
    "field.testInertia": "Test Inertia",
    "field.testSet": "Test Set",
    "field.trainDataset": "Train Dataset",
    "field.type": "Type",
    "field.updated": "Updated",
    "field.versions": "Versions",
    "field.visibility": "Visibility",
    "form.connectApi": "Connect to the local Cortex API, then refresh data",
    "form.editingFailedJob": "Editing failed job {id}. Submit creates a new job.",
    "form.loadingDatasetVersions": "Loading dataset versions",
    "form.noAlias": "No alias",
    "form.noCompatibleDatasetVersions": "No compatible dataset versions",
    "form.noExecutableTemplates": "No executable templates in this API response. Refresh the page or restart the local service.",
    "form.registeredFrom": "Registered from {id}",
    "form.submittingJob": "Submitting job",
    "health.checking": "Checking",
    "health.healthy": "Healthy",
    "health.unavailable": "Unavailable",
    "label.alias": "Alias",
    "lineage.jobRun": "Job / Run",
    "lineage.modelAlias": "Model Alias",
    "locale.label": "Language",
    "metric.datasets": "Datasets",
    "metric.datasetsSingular": "Dataset",
    "metric.jobs": "Jobs",
    "metric.models": "Models",
    "metric.results": "Results",
    "metric.runs": "Runs",
    "metric.tests": "Tests",
    "nav.dashboard": "Dashboard",
    "nav.datasets": "Datasets",
    "nav.models": "Models",
    "nav.results": "Results",
    "nav.runs": "Experiments",
    "nav.tests": "Evaluations",
    "nav.training": "Training",
    "page.datasetDetail": "Dataset detail",
    "page.evaluationDetail": "Evaluation detail",
    "page.jobDetail": "Job detail",
    "page.modelDetail": "Model detail",
    "page.projects": "Projects",
    "page.resultDetail": "Result detail",
    "page.runDetail": "Run detail",
    "page.trainingJobs": "Training Jobs",
    "page.workspace": "Workspace",
    "section.artifacts": "Artifacts",
    "section.inputs": "Inputs",
    "section.lineage": "Lineage",
    "section.logs": "Logs",
    "section.metadata": "Metadata",
    "section.metrics": "Metrics",
    "section.preview": "Preview",
    "section.projectLink": "Project link",
    "section.params": "Params",
    "section.runMetrics": "Run Metrics",
    "section.tags": "Tags",
    "section.versions": "Versions",
    "select.dataset": "Select a dataset",
    "select.evaluation": "Select an evaluation",
    "select.model": "Select a model",
    "select.result": "Select a result",
    "select.run": "Select an experiment run",
    "select.trainingJob": "Select a training job",
    "table.noDatasets": "No datasets",
    "table.noEvaluations": "No tests",
    "table.noJobs": "No jobs",
    "table.noModels": "No models",
    "table.noResults": "No results",
    "table.noRuns": "No runs",
  },
};

function t(key, params = {}) {
  const messages = I18N[state.locale] || I18N[DEFAULT_LOCALE];
  const fallback = I18N[DEFAULT_LOCALE][key] || key;
  return String(messages[key] || fallback).replace(/\{(\w+)\}/g, (_, name) => params[name] ?? "");
}

function readInitialLocale() {
  try {
    const stored = localStorage.getItem(LOCALE_STORAGE_KEY);
    return I18N[stored] ? stored : DEFAULT_LOCALE;
  } catch (error) {
    return DEFAULT_LOCALE;
  }
}

function renderStaticI18n() {
  document.documentElement.lang = state.locale;
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((node) => {
    node.title = t(node.dataset.i18nTitle);
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((node) => {
    node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel));
  });
  const localeSelect = $("#localeSelect");
  if (localeSelect) localeSelect.value = state.locale;
}

function setLocale(locale) {
  if (!I18N[locale] || locale === state.locale) return;
  state.locale = locale;
  try {
    localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch (error) {
    // Ignore storage failures; the active page can still switch language.
  }
  renderStaticI18n();
  if (state.dashboard) render();
}

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
    throw new Error(t("error.apiReach", { target }));
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
  if (!value) return t("common.empty");
  return value.length > 18 ? `${value.slice(0, 8)}...${value.slice(-6)}` : value;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function pill(status) {
  const raw = status || t("common.unknown");
  const normalized = String(status || "unknown").toLowerCase();
  return `<span class="pill ${escapeHtml(normalized)}">${escapeHtml(raw)}</span>`;
}

function progressBar(percent, message = "") {
  const value = Math.max(0, Math.min(100, Number(percent || 0)));
  return `
    <div class="progress-wrap" aria-label="${escapeHtml(t("aria.progress", { value }))}">
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
            <span>${expanded ? t("common.showLess") : t("common.viewMore", { count: items.length - 5 })}</span>
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
    state.dashboard = state.currentProjectId
      ? await api(`/api/v1/projects/${encodeURIComponent(state.currentProjectId)}/dashboard`)
      : await api("/api/v1/dashboard");
    state.projects = state.dashboard.projects || [];
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
  $("#healthText").textContent = status === "ok" ? t("health.healthy") : status === "bad" ? t("health.unavailable") : t("health.checking");
}

function render() {
  const { summary, datasets, jobs, runs, models } = state.dashboard;
  const inProject = Boolean(state.currentProjectId);
  ensureSelections();
  document.body.classList.toggle("project-mode", inProject);
  document.body.classList.toggle("workspace-mode", !inProject);
  renderProjectCards();
  $("#projectLanding").hidden = inProject;
  $("#projectWorkspace").hidden = !inProject;
  $("#projectBackButton").hidden = !inProject;
  $("#lastUpdated").textContent = `${state.locale === "zh-CN" ? "已同步" : "Synced"} ${new Date().toLocaleTimeString(state.locale)}`;
  if (!inProject) {
    applyView("dashboard");
    return;
  }
  $("#metricDatasets").textContent = summary.datasets;
  $("#metricJobs").textContent = summary.jobs;
  $("#metricRuns").textContent = summary.runs;
  $("#metricModels").textContent = summary.models;
  $("#metricTests").textContent = summary.evaluations;
  $("#metricResults").textContent = summary.experimentResults || 0;
  $("#emptyState").classList.toggle("visible", summary.datasets === 0 && summary.jobs === 0 && summary.models === 0);

  $("#datasetCount").textContent = t("common.records", { count: datasets.length });
  $("#datasetsBody").innerHTML = limitedRows(
    "datasets",
    datasets,
    6,
    (dataset) =>
      `<tr ${clickableRow("dataset", dataset.id)}><td>${escapeHtml(dataset.name)}</td><td>${escapeHtml(dataset.type)}</td><td>${dataset.versionCount || 0}</td><td>${escapeHtml(dataset.latestVersion || "")}</td><td>${escapeHtml(dataset.owner)}</td><td>${pill(dataset.status)}</td></tr>`,
    t("table.noDatasets"),
  );

  $("#jobCount").textContent = t("common.records", { count: jobs.length });
  $("#jobsBody").innerHTML = limitedRows(
    "jobs",
    jobs,
    5,
    (job) =>
      `<tr ${clickableRow("job", job.id)}><td class="mono">${shortId(job.id)}</td><td>${escapeHtml(job.templateId)}</td><td>${pill(job.status)}${progressBar(job.progressPercent, job.statusMessage)}</td><td class="mono">${shortId(job.mlflowRunId)}</td><td>${escapeHtml(job.owner)}</td></tr>`,
    t("table.noJobs"),
  );

  $("#runCount").textContent = t("common.records", { count: runs.length });
  $("#runsBody").innerHTML = limitedRows(
    "runs",
    runs,
    5,
    (run) => {
      const dataset = run.tags?.dataset_version || t("common.empty");
      const inertia = run.metrics?.inertia ?? "";
      const rows = run.metrics?.rows ?? "";
      return `<tr ${clickableRow("run", run.id)}><td class="mono">${shortId(run.id)}</td><td>${pill(run.status)}</td><td>${escapeHtml(dataset)}</td><td>${escapeHtml(inertia)}</td><td>${escapeHtml(rows)}</td></tr>`;
    },
    t("table.noRuns"),
  );

  $("#modelCount").textContent = t("common.records", { count: models.length });
  $("#modelsBody").innerHTML = limitedRows(
    "models",
    models,
    4,
    (model) =>
      `<tr ${clickableRow("model", model.name)}><td>${escapeHtml(model.name)}</td><td>${model.versions.length}</td><td>${escapeHtml(model.aliases.champion || "")}</td><td>${escapeHtml(model.aliases.challenger || "")}</td></tr>`,
    t("table.noModels"),
  );

  const results = rankedResults(state.dashboard.experimentResults || []);
  $("#resultCount").textContent = t("common.records", { count: results.length });
  $("#resultsBody").innerHTML = limitedRows(
    "results",
    results,
    8,
    (result) =>
      `<tr ${clickableRow("result", result.id)}><td>${result.rank}</td><td>${escapeHtml(result.methodId)}</td><td>${escapeHtml(result.methodKind || "")}</td><td>${metricValue(result.metrics?.rmse)}</td><td>${metricValue(result.metrics?.mae)}</td><td>${metricValue(result.metrics?.r2)}</td><td>${metricValue(result.metrics?.mape)}</td><td>${metricValue(result.metrics?.cv)}</td></tr>`,
    t("table.noResults"),
  );

  const evaluations = state.dashboard.evaluations || [];
  $("#testCount").textContent = t("common.records", { count: evaluations.length });
  $("#testsBody").innerHTML = limitedRows(
    "evaluations",
    evaluations,
    6,
    (evaluation) =>
      `<tr ${clickableRow("evaluation", evaluation.id)}><td class="mono">${shortId(evaluation.id)}</td><td>${escapeHtml(evaluation.registeredModelName)}:${escapeHtml(evaluation.modelVersion)}</td><td>${escapeHtml(evaluation.trainDatasetRef)}</td><td>${escapeHtml(evaluation.testDatasetRef)}</td><td>${escapeHtml(evaluation.metrics.test_inertia)}</td><td>${pill(evaluation.status)}</td></tr>`,
    t("table.noEvaluations"),
  );

  renderAllDetails();
  renderTrainingForm();
  renderLineage();
  renderChart(runs);
  applyView(state.activeView);
}

function renderProjectCards() {
  const projects = state.projects || [];
  $("#projectCount").textContent = t("common.records", { count: projects.length });
  $("#projectCards").innerHTML = projects.length
    ? projects
        .map((project) => {
          const summary = project.summary || {};
          return `
            <button class="project-card" type="button" data-select-project="${escapeHtml(project.id)}">
              <span class="project-card-title">${escapeHtml(project.name)}</span>
              <span class="project-card-description">${escapeHtml(project.description || project.id)}</span>
              <span class="project-card-meta">${escapeHtml(project.owner)} · ${escapeHtml(project.team)} · ${escapeHtml(project.status)}</span>
              <span class="project-card-stats">
                <span>${summary.datasets || 0} ${t("metric.datasets")}</span>
                <span>${summary.jobs || 0} ${t("metric.jobs")}</span>
                <span>${summary.runs || 0} ${t("metric.runs")}</span>
                <span>${summary.models || 0} ${t("metric.models")}</span>
              </span>
            </button>
          `;
        })
        .join("")
    : `<p class="muted">${t("common.noProjects")}</p>`;
  const datasets = state.dashboard?.datasets || [];
  const catalogCount = $("#catalogDatasetCount");
  const catalogBody = $("#catalogDatasetsBody");
  if (catalogCount) catalogCount.textContent = t("common.records", { count: datasets.length });
  if (catalogBody) {
    catalogBody.innerHTML = limitedRows(
      "datasets",
      datasets,
      6,
      (dataset) =>
        `<tr ${clickableRow("dataset", dataset.id)}><td>${escapeHtml(dataset.name)}</td><td>${escapeHtml(dataset.type)}</td><td>${dataset.versionCount || 0}</td><td>${escapeHtml(dataset.latestVersion || "")}</td><td>${escapeHtml(dataset.owner)}</td><td>${pill(dataset.status)}</td></tr>`,
      t("table.noDatasets"),
    );
  }
  renderCatalogDatasetDetail();
}

function ensureSelections() {
  const { datasets, jobs, runs, models, evaluations = [], experimentResults = [] } = state.dashboard;
  state.selected.dataset = datasets.some((item) => item.id === state.selected.dataset) ? state.selected.dataset : datasets[0]?.id || null;
  state.selected.job = jobs.some((item) => item.id === state.selected.job) ? state.selected.job : jobs[0]?.id || null;
  state.selected.run = runs.some((item) => item.id === state.selected.run) ? state.selected.run : runs[0]?.id || null;
  state.selected.model = models.some((item) => item.name === state.selected.model) ? state.selected.model : models[0]?.name || null;
  state.selected.result = experimentResults.some((item) => item.id === state.selected.result) ? state.selected.result : experimentResults[0]?.id || null;
  state.selected.evaluation = evaluations.some((item) => item.id === state.selected.evaluation) ? state.selected.evaluation : evaluations[0]?.id || null;
  state.selectedRun = runs.find((run) => run.id === state.selected.run) || runs[0] || null;
}

function renderLineage() {
  const run = state.selectedRun;
  const models = state.dashboard?.models || [];
  const datasetRef = run?.tags?.dataset_version || t("common.empty");
  const linkedModel = models.find((model) => model.versions.some((version) => version.runId === run?.id));
  const alias = linkedModel
    ? Object.entries(linkedModel.aliases)
        .map(([name, version]) => `${name}:${version}`)
        .join(", ") || t("common.versioned")
    : t("common.empty");
  $("#lineageLabel").textContent = run ? shortId(run.id) : t("common.noRunSelected");
  $("#lineageDataset").textContent = shortId(datasetRef);
  $("#lineageRun").textContent = shortId(run?.id);
  $("#lineageModel").textContent = linkedModel ? `${linkedModel.name} ${alias}` : t("common.empty");
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
    ctx.fillText(t("common.noRunMetrics"), 24, 92);
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
  if (type === "result") return (data.experimentResults || []).find((item) => item.id === id);
  if (type === "evaluation") return (data.evaluations || []).find((item) => item.id === id);
  return null;
}

function rankedResults(results) {
  return [...results]
    .sort((left, right) => Number(left.metrics?.rmse ?? Number.POSITIVE_INFINITY) - Number(right.metrics?.rmse ?? Number.POSITIVE_INFINITY))
    .map((result, index) => ({ ...result, rank: index + 1 }));
}

function metricValue(value) {
  if (value === null || value === undefined || value === "") return "";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return escapeHtml(value);
  return escapeHtml(Number(numeric.toFixed(6)));
}

function detailKey(type, id) {
  return `${type}:${id}`;
}

function rememberDatasetVersions(datasetId, versions) {
  for (const version of versions || []) {
    if (!version.id) continue;
    state.datasetVersionTargets[version.id] = {
      datasetId,
      versionId: version.id,
      version: version.version || "",
    };
  }
}

function findDatasetVersionTarget(versionId) {
  if (!versionId) return null;
  const cached = state.datasetVersionTargets[versionId];
  if (cached) {
    if (findResource("dataset", cached.datasetId)) return cached;
    delete state.datasetVersionTargets[versionId];
  }
  for (const dataset of state.dashboard?.datasets || []) {
    const versions = state.details[detailKey("dataset", dataset.id)]?.versions || [];
    const version = versions.find((item) => item.id === versionId);
    if (version) {
      rememberDatasetVersions(dataset.id, versions);
      return state.datasetVersionTargets[versionId];
    }
  }
  return null;
}

async function loadDatasetVersionTarget(versionId) {
  if (!versionId) return null;
  const existing = findDatasetVersionTarget(versionId);
  if (existing) return existing;
  for (const dataset of state.dashboard?.datasets || []) {
    const versions = await api(`/api/v1/datasets/${encodeURIComponent(dataset.id)}/versions`);
    rememberDatasetVersions(dataset.id, versions);
    const target = findDatasetVersionTarget(versionId);
    if (target) return target;
  }
  return null;
}

function renderDatasetVersionLink(versionId) {
  if (!versionId) return t("common.empty");
  const target = findDatasetVersionTarget(versionId);
  const label = `<span class="mono">${escapeHtml(versionId)}</span>`;
  if (!target) return label;
  return `<button class="link-button compact-link" data-jump-dataset-version="${escapeHtml(versionId)}">${label}</button>`;
}

function detailList(items) {
  return `<dl class="detail-grid">${items.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${value || t("common.empty")}</dd></div>`).join("")}</dl>`;
}

function jsonBlock(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2);
  return `<pre class="detail-json">${escapeHtml(text || t("common.empty"))}</pre>`;
}

function renderCollection(items, emptyLabel = t("common.empty")) {
  if (!items?.length) return `<p class="muted">${escapeHtml(emptyLabel)}</p>`;
  return `<ul class="detail-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function renderPreviewTable(preview) {
  if (!preview) return "";
  const columns = preview.schema?.columns?.map((column) => column.name) || Object.keys(preview.rows?.[0] || {});
  const rows = preview.rows || [];
  const table = rows.length
    ? `
      <div class="table-wrap compact-table">
        <table>
          <thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
          <tbody>${rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(row[column] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody>
        </table>
      </div>
    `
    : `<p class="muted">${t("common.empty")}</p>`;
  const profile = preview.profile || {};
  return `
    <section class="preview-panel">
      <h4>${t("section.preview")} · DatasetVersion ${escapeHtml(preview.version || "")}</h4>
      <p class="muted">${escapeHtml(preview.storageUri || "")} · ${t("field.rows")} ${escapeHtml(profile.rows ?? rows.length)}${preview.truncated ? " · truncated" : ""}</p>
      ${table}
    </section>
  `;
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
            <span>${t("field.modelName")}</span>
            <input name="modelName" value="${escapeHtml(defaultModelName(run))}" required />
          </label>
          <label>
            <span>${t("label.alias")}</span>
            <select name="alias">
              <option value="">${t("form.noAlias")}</option>
              <option value="challenger">challenger</option>
              <option value="champion">champion</option>
            </select>
          </label>
          <label>
            <span>${t("field.description")}</span>
            <input name="description" value="${escapeHtml(t("form.registeredFrom", { id: shortId(run.id) }))}" />
          </label>
        </div>
        <div class="form-footer">
          <p class="${state.registrationForm.error ? "form-error" : ""}">${escapeHtml(state.registrationForm.error)}</p>
          <div class="toolbar">
            <button class="secondary-button" type="button" data-cancel-register>${t("action.cancel")}</button>
            <button class="primary-button" type="submit" ${state.registrationForm.submitting ? "disabled" : ""}>${t("action.registerModelVersion")}</button>
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
  renderTrainingDefaults();
  renderJobFormStatus();
}

function renderTemplateOptions() {
  const select = $("#jobTemplate");
  if (!select || !state.dashboard) return;
  const current = state.trainingForm.defaults.templateId || select.value;
  const templates = executableTemplates();
  select.innerHTML = templates.map((template) => `<option value="${escapeHtml(template.id)}">${escapeHtml(template.name)} · ${escapeHtml(template.id)}</option>`).join("");
  select.disabled = !templates.length;
  if (templates.some((template) => template.id === current)) select.value = current;
  state.trainingForm.defaults.templateId = "";
}

function compatibleVersions(template) {
  const datasetTypes = template?.datasetTypes || [];
  return state.trainingForm.versions.filter((item) => item.datasetStatus !== "archived" && item.trainable && (!datasetTypes.length || datasetTypes.includes(item.datasetType)));
}

function renderDatasetOptions() {
  const select = $("#jobDataset");
  if (!select) return;
  const selected = state.trainingForm.defaults.datasetRef || select.value;
  const template = currentTemplate();
  const versions = compatibleVersions(template);
  if (state.trainingForm.loadingVersions) {
    select.innerHTML = `<option value="">${t("form.loadingDatasetVersions")}</option>`;
    select.disabled = true;
    return;
  }
  select.disabled = !versions.length;
  select.innerHTML = versions.length
    ? versions.map((item) => `<option value="${escapeHtml(item.ref)}">${escapeHtml(item.datasetName)}@${escapeHtml(item.version)} · ${escapeHtml(item.datasetType)}</option>`).join("")
    : `<option value="">${t("form.noCompatibleDatasetVersions")}</option>`;
  if (versions.some((item) => item.ref === selected)) select.value = selected;
  state.trainingForm.defaults.datasetRef = "";
}

function renderParamInputs() {
  const container = $("#jobParams");
  const template = currentTemplate();
  if (!container || !template) {
    if (container) container.innerHTML = "";
    return;
  }
  const schema = template.paramSchema || {};
  const defaultParams = state.trainingForm.defaults.params || {};
  container.innerHTML = Object.entries(schema)
    .map(([name, type]) => {
      const inputType = type === "int" || type === "float" ? "number" : "text";
      const step = type === "float" ? "any" : "1";
      const value = defaultParams[name] ??
        (name === "n_clusters" ? "3" :
          name === "random_state" ? "42" :
          name === "target" ? "price" :
          name === "periods" ? "24" :
          name === "trend" ? "additive" :
          name === "max_iter" ? "100" :
          "");
      return `<label><span>${escapeHtml(name)}</span><input name="param:${escapeHtml(name)}" type="${inputType}" step="${step}" value="${escapeHtml(value)}" /></label>`;
    })
    .join("");
  state.trainingForm.defaults.params = null;
}

function renderTrainingDefaults() {
  const defaults = state.trainingForm.defaults;
  if (defaults.experimentName) $("#jobExperiment").value = defaults.experimentName;
  if (defaults.owner) $("#jobForm [name='owner']").value = defaults.owner;
  if (defaults.team) $("#jobForm [name='team']").value = defaults.team;
  state.trainingForm.defaults.experimentName = "";
  state.trainingForm.defaults.owner = "";
  state.trainingForm.defaults.team = "";
}

function renderJobFormStatus() {
  const status = $("#jobFormStatus");
  if (!status) return;
  if (!state.dashboard) {
    status.textContent = t("form.connectApi");
    status.className = "form-error";
  } else if (!executableTemplates().length) {
    status.textContent = t("form.noExecutableTemplates");
    status.className = "form-error";
  } else if (state.trainingForm.error) {
    status.textContent = state.trainingForm.error;
    status.className = "form-error";
  } else if (state.trainingForm.submitting) {
    status.textContent = t("form.submittingJob");
    status.className = "";
  } else if (state.trainingForm.sourceJobId) {
    status.textContent = t("form.editingFailedJob", { id: shortId(state.trainingForm.sourceJobId) });
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
  renderCatalogDatasetDetail();
  renderDatasetDetail();
  renderJobDetail();
  renderRunDetail();
  renderModelDetail();
  renderResultDetail();
  renderEvaluationDetail();
}

function datasetDetailBody(dataset) {
  const extra = state.details[detailKey("dataset", dataset.id)];
  const versions = extra?.versions || [];
  const lineage = extra?.lineage || [];
  const preview = extra?.selectedPreview ? extra.preview?.[extra.selectedPreview] : null;
  const archiveAction = dataset.status === "archived"
    ? `<button class="secondary-button" data-restore-dataset="${escapeHtml(dataset.id)}">${t("action.restoreDataset")}</button>`
    : `<button class="secondary-button danger-button" data-archive-dataset="${escapeHtml(dataset.id)}">${t("action.archiveDataset")}</button>`;
  const unlinkAction = state.currentProjectId && dataset.projectLink
    ? `<button class="secondary-button" data-unlink-project-dataset="${escapeHtml(dataset.id)}">${t("action.removeFromProject")}</button>`
    : "";
  const metadataForm = `
    <section class="inline-form compact-form">
      <form data-dataset-metadata-form="${escapeHtml(dataset.id)}">
        <div class="form-grid">
          <label><span>${t("field.name")}</span><input name="name" value="${escapeHtml(dataset.name)}" required /></label>
          <label><span>${t("field.description")}</span><input name="description" value="${escapeHtml(dataset.description || "")}" /></label>
          <label><span>${t("field.tags")}</span><input name="tags" value="${escapeHtml((dataset.tags || []).join(", "))}" /></label>
          <label><span>${t("field.domain")}</span><input name="domain" value="${escapeHtml(dataset.domain || "")}" /></label>
          <label><span>${t("field.source")}</span><input name="sourceSystem" value="${escapeHtml(dataset.sourceSystem || "")}" /></label>
          <label>
            <span>${t("field.visibility")}</span>
            <select name="visibility">
              ${["private", "team", "public"].map((value) => `<option value="${value}" ${dataset.visibility === value ? "selected" : ""}>${value}</option>`).join("")}
            </select>
          </label>
        </div>
        <div class="form-footer">
          <p>${t("field.id")} <span class="mono">${escapeHtml(dataset.id)}</span></p>
          <button class="secondary-button" type="submit">${t("action.editMetadata")}</button>
        </div>
      </form>
    </section>
  `;
  const versionTable = versions.length
    ? `
      <div class="table-wrap compact-table">
        <table>
          <thead>
            <tr><th>${t("field.datasetVersion")}</th><th>${t("field.type")}</th><th>${t("field.rows")}</th><th>Checksum</th><th>${t("field.status")}</th><th>Actions</th></tr>
          </thead>
          <tbody>
            ${versions
              .map(
                (version) => `
                  <tr>
                    <td><span class="mono">DatasetVersion ${escapeHtml(version.version)}</span></td>
                    <td>${escapeHtml(version.format)}</td>
                    <td>${escapeHtml(version.rowCount ?? t("common.unknown"))}</td>
                    <td>${escapeHtml(version.checksumStatus)} · ${escapeHtml(shortId(version.checksum || ""))}</td>
                    <td>${version.trainable ? "trainable" : "disabled"} · ${escapeHtml(version.approvalStatus || "")}</td>
                    <td>
                      <div class="inline-actions horizontal-actions">
                        <button class="link-button" data-preview-dataset-version="${escapeHtml(version.version)}">${t("action.preview")}</button>
                        <button class="link-button" data-use-dataset-version="${escapeHtml(`${dataset.id}@${version.version}`)}">${t("action.useForTraining")}</button>
                      </div>
                    </td>
                  </tr>
                `,
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `
    : `<p class="muted">${extra ? t("common.noVersions") : t("common.loadingVersions")}</p>`;
  const projectLink = dataset.projectLink
    ? detailList([
        ["Role", escapeHtml(dataset.projectLink.role)],
        ["Version policy", escapeHtml(dataset.projectLink.versionPolicy)],
        ["Pinned version", escapeHtml(dataset.projectLink.pinnedVersion || t("common.empty"))],
      ])
    : `<p class="muted">${state.currentProjectId ? t("common.empty") : "Workspace catalog"}</p>`;
  return `<div class="detail-actions">${archiveAction}${unlinkAction}</div>` +
      `<h4>${t("section.metadata")}</h4>` +
      metadataForm +
      detailList([
        [t("field.id"), `<span class="mono">${escapeHtml(dataset.id)}</span>`],
        [t("field.type"), escapeHtml(dataset.type)],
        [t("field.owner"), escapeHtml(dataset.owner)],
        [t("field.team"), escapeHtml(dataset.team)],
        [t("field.status"), pill(dataset.status)],
        [t("field.created"), escapeHtml(dataset.createdAt)],
        [t("field.updated"), escapeHtml(dataset.updatedAt)],
      ]) +
      `<h4>${t("section.versions")}</h4>${versionTable}` +
      renderPreviewTable(preview) +
      `<h4>${t("section.projectLink")}</h4>${projectLink}` +
      `<h4>${t("section.lineage")}</h4>${lineage.length ? detailList(lineage.map((item) => [shortId(item.mlflowRunId), `${escapeHtml(item.jobStatus)} · ${escapeHtml(item.registeredModelName || t("common.noModel"))}${item.modelVersion ? `:${escapeHtml(item.modelVersion)}` : ""}`])) : `<p class="muted">${extra ? t("common.noDownstreamRuns") : t("common.loadingLineage")}</p>`}`;
}

function renderCatalogDatasetDetail() {
  const container = $("#catalogDatasetDetail");
  if (!container) return;
  const dataset = findResource("dataset", state.selected.dataset);
  if (!dataset) {
    setDetail("#catalogDatasetDetail", t("page.datasetDetail"), t("select.dataset"), "");
    return;
  }
  setDetail("#catalogDatasetDetail", dataset.name, dataset.description || dataset.id, datasetDetailBody(dataset));
}

function renderDatasetDetail() {
  const dataset = findResource("dataset", state.selected.dataset);
  if (!dataset) {
    setDetail("#datasetDetail", t("page.datasetDetail"), t("select.dataset"), "");
    return;
  }
  setDetail("#datasetDetail", dataset.name, dataset.description || dataset.id, datasetDetailBody(dataset));
}

function renderJobDetail() {
  const job = findResource("job", state.selected.job);
  if (!job) {
    setDetail("#jobDetail", t("page.jobDetail"), t("select.trainingJob"), "");
    return;
  }
  const extra = state.details[detailKey("job", job.id)];
  const registered = modelVersionForRun(job.mlflowRunId);
  const jobRun = findResource("run", job.mlflowRunId);
  const registerAction = canRegisterRun(jobRun)
    ? `<button class="link-button" data-register-run="${escapeHtml(job.mlflowRunId)}"><span>${t("action.registerAsModel")}</span></button>`
    : "";
  const resubmitAction = job.status === "failed" ? `<button class="secondary-button" data-edit-failed-job="${escapeHtml(job.id)}">${state.locale === "zh-CN" ? "编辑并重新提交" : "Edit and resubmit"}</button>` : "";
  setDetail(
    "#jobDetail",
    shortId(job.id),
    job.experimentName,
    detailList([
      [t("field.id"), `<span class="mono">${escapeHtml(job.id)}</span>`],
      [t("field.template"), escapeHtml(job.templateId)],
      [t("field.project"), `<span class="mono">${escapeHtml(job.projectId || t("common.empty"))}</span>`],
      [t("field.status"), pill(job.status)],
      [t("field.progress"), progressBar(job.progressPercent, job.statusMessage)],
      [t("field.datasetVersionId"), renderDatasetVersionLink(job.datasetVersionId)],
      [
        t("field.run"),
        job.mlflowRunId
          ? `<div class="inline-actions"><button class="link-button" data-jump-run="${escapeHtml(job.mlflowRunId)}"><span class="mono">${escapeHtml(job.mlflowRunId)}</span><span>${t("action.viewTrainingResults")}</span></button>${registerAction}</div>`
          : t("common.empty"),
      ],
      [t("field.modelRegistry"), registered ? `${escapeHtml(registered.model.name)}:${escapeHtml(registered.version.version)}` : t("common.notRegistered")],
      [t("field.owner"), escapeHtml(job.owner)],
      [t("field.created"), escapeHtml(job.createdAt)],
      [t("field.started"), escapeHtml(job.startedAt)],
      [t("field.finished"), escapeHtml(job.finishedAt)],
      [t("field.error"), escapeHtml(job.errorMessage)],
    ]) +
      `<h4>${t("section.params")}</h4>${jsonBlock(job.params)}` +
      resubmitAction +
      `<h4>${t("section.logs")}</h4>${jsonBlock(extra?.logs ?? (extra ? "" : t("common.loadingLogs")))}`,
  );
}

function renderRunDetail() {
  const run = findResource("run", state.selected.run);
  if (!run) {
    setDetail("#runDetail", t("page.runDetail"), t("select.run"), "");
    return;
  }
  const registered = modelVersionForRun(run.id);
  const registryValue = registered
    ? `${escapeHtml(registered.model.name)}:${escapeHtml(registered.version.version)}`
    : canRegisterRun(run)
      ? `<button class="secondary-button" data-open-register-run="${escapeHtml(run.id)}">${t("action.registerAsModel")}</button>`
      : t("common.notRegisterable");
  setDetail(
    "#runDetail",
    shortId(run.id),
    run.experimentName,
    detailList([
      [t("field.id"), `<span class="mono">${escapeHtml(run.id)}</span>`],
      [t("field.status"), pill(run.status)],
      [t("field.experiment"), escapeHtml(run.experimentName)],
      [t("field.project"), `<span class="mono">${escapeHtml(run.platform?.projectId || run.tags?.["platform.projectId"] || t("common.empty"))}</span>`],
      [t("field.job"), `<span class="mono">${escapeHtml(run.platform?.jobId || t("common.empty"))}</span>`],
      [t("field.dataset"), escapeHtml(run.tags?.dataset_version || "")],
      [t("field.modelRegistry"), registryValue],
      [t("field.created"), escapeHtml(run.createdAt)],
      [t("field.ended"), escapeHtml(run.endedAt)],
    ]) +
      renderRegistrationForm(run) +
      `<h4>${t("section.metrics")}</h4>${jsonBlock(run.metrics)}` +
      `<h4>${t("section.params")}</h4>${jsonBlock(run.params)}` +
      `<h4>${t("section.tags")}</h4>${jsonBlock(run.tags)}` +
      `<h4>${t("section.inputs")}</h4>${jsonBlock(run.inputs)}` +
      `<h4>${t("section.artifacts")}</h4>${renderCollection(run.artifacts, t("common.noArtifacts"))}`,
  );
}

function renderModelDetail() {
  const model = findResource("model", state.selected.model);
  if (!model) {
    setDetail("#modelDetail", t("page.modelDetail"), t("select.model"), "");
    return;
  }
  setDetail(
    "#modelDetail",
    model.name,
    t("common.records", { count: model.versions.length }),
    detailList([
      [t("field.name"), escapeHtml(model.name)],
      [t("field.champion"), escapeHtml(model.aliases.champion || t("common.empty"))],
      [t("field.challenger"), escapeHtml(model.aliases.challenger || t("common.empty"))],
      [t("field.created"), escapeHtml(model.createdAt)],
    ]) +
      `<h4>${t("section.versions")}</h4>${model.versions.length ? detailList(model.versions.map((version) => [`${t("field.versions")} ${version.version}`, `${t("field.run")} ${escapeHtml(shortId(version.runId))} · ${escapeHtml(version.artifactPath)} · ${escapeHtml(version.description || t("common.noDescription"))}`])) : `<p class="muted">${t("common.noVersions")}</p>`}`,
  );
}

function renderResultDetail() {
  const result = findResource("result", state.selected.result);
  if (!result) {
    setDetail("#resultDetail", t("page.resultDetail"), t("select.result"), "");
    return;
  }
  setDetail(
    "#resultDetail",
    result.methodId,
    result.experimentName,
    detailList([
      [t("field.id"), `<span class="mono">${escapeHtml(result.id)}</span>`],
      [t("field.experiment"), escapeHtml(result.experimentName)],
      [t("field.method"), escapeHtml(result.methodId)],
      [t("field.kind"), escapeHtml(result.methodKind || t("common.empty"))],
      [t("field.dataset"), escapeHtml(result.datasetRef || t("common.empty"))],
      [t("field.artifact"), escapeHtml(result.artifactUri || t("common.empty"))],
      [t("field.createdBy"), escapeHtml(result.createdBy)],
      [t("field.created"), escapeHtml(result.createdAt)],
    ]) + `<h4>${t("section.metrics")}</h4>${jsonBlock(result.metrics)}`,
  );
}

function renderEvaluationDetail() {
  const evaluation = findResource("evaluation", state.selected.evaluation);
  if (!evaluation) {
    setDetail("#evaluationDetail", t("page.evaluationDetail"), t("select.evaluation"), "");
    return;
  }
  setDetail(
    "#evaluationDetail",
    shortId(evaluation.id),
    `${evaluation.registeredModelName}:${evaluation.modelVersion}`,
    detailList([
      [t("field.id"), `<span class="mono">${escapeHtml(evaluation.id)}</span>`],
      [t("field.model"), `${escapeHtml(evaluation.registeredModelName)}:${escapeHtml(evaluation.modelVersion)}`],
      [t("field.status"), pill(evaluation.status)],
      [t("field.run"), `<span class="mono">${escapeHtml(evaluation.runId)}</span>`],
      [t("field.trainDataset"), escapeHtml(evaluation.trainDatasetRef)],
      [t("field.testDataset"), escapeHtml(evaluation.testDatasetRef)],
      [t("field.owner"), escapeHtml(evaluation.owner)],
      [t("field.created"), escapeHtml(evaluation.createdAt)],
    ]) + `<h4>${t("section.metrics")}</h4>${jsonBlock(evaluation.metrics)}`,
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
  if (!state.currentProjectId) return;
  state.trainingForm.open = true;
  state.trainingForm.error = "";
  state.trainingForm.sourceJobId = null;
  state.trainingForm.defaults = {};
  renderTrainingForm();
  await loadTrainingVersions();
}

function closeTrainingForm() {
  state.trainingForm.open = false;
  state.trainingForm.error = "";
  state.trainingForm.sourceJobId = null;
  state.trainingForm.defaults = {};
  renderTrainingForm();
}

async function editFailedJob(jobId) {
  const job = findResource("job", jobId);
  if (!job || job.status !== "failed") return;
  state.trainingForm.open = true;
  state.trainingForm.error = "";
  state.trainingForm.sourceJobId = job.id;
  await loadTrainingVersions();
  const version = state.trainingForm.versions.find((item) => item.id === job.datasetVersionId);
  state.trainingForm.defaults = {
    templateId: job.templateId,
    datasetRef: version?.ref || "",
    experimentName: job.experimentName,
    owner: job.owner,
    team: job.team,
    params: { ...(job.params || {}) },
  };
  renderTrainingForm();
  $("#trainingJobForm").scrollIntoView({ block: "nearest" });
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
          datasetStatus: dataset.status,
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
        projectId: state.currentProjectId,
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
    state.trainingForm.sourceJobId = null;
    state.trainingForm.defaults = {};
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

async function submitDatasetMetadata(event) {
  const form = event.target.closest("[data-dataset-metadata-form]");
  if (!form) return;
  event.preventDefault();
  const datasetId = form.dataset.datasetMetadataForm;
  const data = new FormData(form);
  const tags = String(data.get("tags") || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const updated = await api(`/api/v1/datasets/${encodeURIComponent(datasetId)}`, {
    method: "PATCH",
    body: JSON.stringify({
      name: data.get("name"),
      description: data.get("description"),
      tags,
      domain: data.get("domain"),
      sourceSystem: data.get("sourceSystem"),
      visibility: data.get("visibility"),
    }),
  });
  const index = state.dashboard.datasets.findIndex((item) => item.id === datasetId);
  if (index >= 0) state.dashboard.datasets[index] = { ...state.dashboard.datasets[index], ...updated };
  delete state.details[detailKey("dataset", datasetId)];
  state.selected.dataset = datasetId;
  render();
  await loadResourceDetail("dataset", datasetId);
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
      rememberDatasetVersions(id, versions);
      const latest = dataset?.latestVersion;
      const lineage = latest ? await api(`/api/v1/datasets/${encodeURIComponent(id)}/versions/${encodeURIComponent(latest)}/runs`) : [];
      state.details[key] = { versions, lineage };
    } else if (type === "job") {
      const logs = await api(`/api/v1/training/jobs/${encodeURIComponent(id)}/logs`);
      state.details[key] = logs;
      const job = findResource("job", id);
      await loadDatasetVersionTarget(job?.datasetVersionId);
    } else {
      state.details[key] = {};
    }
  } catch (error) {
    state.details[key] = { error: error.message };
  }
  renderAllDetails();
}

async function previewDatasetVersion(version) {
  const dataset = findResource("dataset", state.selected.dataset);
  if (!dataset || !version) return;
  const key = detailKey("dataset", dataset.id);
  if (!state.details[key]) await loadResourceDetail("dataset", dataset.id);
  try {
    const preview = await api(`/api/v1/datasets/${encodeURIComponent(dataset.id)}/versions/${encodeURIComponent(version)}/preview?limit=50`);
    state.details[key] = {
      ...(state.details[key] || {}),
      preview: {
        ...(state.details[key]?.preview || {}),
        [version]: preview,
      },
      selectedPreview: version,
    };
  } catch (error) {
    state.details[key] = {
      ...(state.details[key] || {}),
      preview: {
        ...(state.details[key]?.preview || {}),
        [version]: { version, rows: [], schema: { columns: [] }, profile: {}, storageUri: error.message },
      },
      selectedPreview: version,
    };
  }
  renderCatalogDatasetDetail();
  renderDatasetDetail();
}

async function useDatasetVersionForTraining(datasetRef) {
  if (!datasetRef) return;
  const datasetId = datasetRef.split("@")[0];
  const dataset = findResource("dataset", datasetId);
  const compatibleTemplate = executableTemplates().find((template) => {
    const types = template.datasetTypes || [];
    return dataset && (!types.length || types.includes(dataset.type));
  });
  state.trainingForm.open = true;
  state.trainingForm.error = "";
  state.trainingForm.defaults = { datasetRef, templateId: compatibleTemplate?.id || "" };
  applyView("training");
  renderTrainingForm();
  await loadTrainingVersions();
  state.trainingForm.defaults = { datasetRef, templateId: compatibleTemplate?.id || "" };
  renderTrainingForm();
}

async function archiveDataset(datasetId) {
  if (!datasetId) return;
  const archived = await api(`/api/v1/datasets/${encodeURIComponent(datasetId)}`, { method: "DELETE" });
  const index = state.dashboard.datasets.findIndex((item) => item.id === datasetId);
  if (index >= 0) state.dashboard.datasets[index] = { ...state.dashboard.datasets[index], ...archived };
  state.trainingForm.versions = [];
  delete state.details[detailKey("dataset", datasetId)];
  render();
  await loadResourceDetail("dataset", datasetId);
}

async function restoreDataset(datasetId) {
  if (!datasetId) return;
  const restored = await api(`/api/v1/datasets/${encodeURIComponent(`${datasetId}:restore`)}`, { method: "POST", body: JSON.stringify({}) });
  const index = state.dashboard.datasets.findIndex((item) => item.id === datasetId);
  if (index >= 0) state.dashboard.datasets[index] = { ...state.dashboard.datasets[index], ...restored };
  state.trainingForm.versions = [];
  delete state.details[detailKey("dataset", datasetId)];
  render();
  await loadResourceDetail("dataset", datasetId);
}

async function unlinkProjectDataset(datasetId) {
  if (!state.currentProjectId || !datasetId) return;
  await api(`/api/v1/projects/${encodeURIComponent(state.currentProjectId)}/datasets/${encodeURIComponent(datasetId)}`, { method: "DELETE" });
  state.dashboard.datasets = state.dashboard.datasets.filter((item) => item.id !== datasetId);
  if (state.dashboard.summary) state.dashboard.summary.datasets = state.dashboard.datasets.length;
  delete state.details[detailKey("dataset", datasetId)];
  state.selected.dataset = state.dashboard.datasets[0]?.id || null;
  state.trainingForm.versions = [];
  render();
}

async function runFullTest() {
  const button = $("#fullTestButton");
  const emptyButton = $("#emptyImportButton");
  if (button) button.disabled = true;
  emptyButton.disabled = true;
  if (button) button.textContent = t("action.creatingExample");
  emptyButton.textContent = t("action.creatingExample");
  try {
    await api("/api/v1/demo/full-test", { method: "POST", body: JSON.stringify({ projectId: state.currentProjectId }) });
    await refresh();
  } finally {
    if (button) button.disabled = false;
    emptyButton.disabled = false;
    if (button) button.textContent = t("action.createExample");
    emptyButton.textContent = t("action.createExample");
  }
}

function applyView(view) {
  if (!state.currentProjectId && view !== "dashboard") view = "dashboard";
  state.activeView = view;
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  document.querySelectorAll(".dashboard-view").forEach((section) => section.classList.toggle("active", section.id === view));
  document.querySelectorAll(".table-view").forEach((section) => section.classList.toggle("active", section.id === view));
  const project = state.dashboard?.project;
  document.querySelector("h1").textContent = project ? project.name : t("page.projects");
  const selectedByView = {
    datasets: ["dataset", state.selected.dataset],
    training: ["job", state.selected.job],
    runs: ["run", state.selected.run],
    models: ["model", state.selected.model],
    results: ["result", state.selected.result],
    tests: ["evaluation", state.selected.evaluation],
  };
  const selection = selectedByView[view];
  if (selection) loadResourceDetail(selection[0], selection[1]);
}

async function jumpToDatasetVersion(versionId) {
  const target = await loadDatasetVersionTarget(versionId);
  if (!target) return;
  state.selected.dataset = target.datasetId;
  applyView("datasets");
  render();
  await loadResourceDetail("dataset", target.datasetId);
}

function bindNav() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => {
      applyView(item.dataset.view);
    });
  });
}

document.addEventListener("click", (event) => {
  const projectButton = event.target.closest("[data-select-project]");
  if (projectButton) {
    event.preventDefault();
    selectProject(projectButton.dataset.selectProject);
    return;
  }
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
  const editFailedButton = event.target.closest("[data-edit-failed-job]");
  if (editFailedButton) {
    event.preventDefault();
    editFailedJob(editFailedButton.dataset.editFailedJob);
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
  const datasetVersionButton = event.target.closest("[data-jump-dataset-version]");
  if (datasetVersionButton) {
    event.preventDefault();
    jumpToDatasetVersion(datasetVersionButton.dataset.jumpDatasetVersion);
    return;
  }
  const previewButton = event.target.closest("[data-preview-dataset-version]");
  if (previewButton) {
    event.preventDefault();
    previewDatasetVersion(previewButton.dataset.previewDatasetVersion);
    return;
  }
  const useVersionButton = event.target.closest("[data-use-dataset-version]");
  if (useVersionButton) {
    event.preventDefault();
    useDatasetVersionForTraining(useVersionButton.dataset.useDatasetVersion);
    return;
  }
  const archiveButton = event.target.closest("[data-archive-dataset]");
  if (archiveButton) {
    event.preventDefault();
    archiveDataset(archiveButton.dataset.archiveDataset);
    return;
  }
  const restoreButton = event.target.closest("[data-restore-dataset]");
  if (restoreButton) {
    event.preventDefault();
    restoreDataset(restoreButton.dataset.restoreDataset);
    return;
  }
  const unlinkButton = event.target.closest("[data-unlink-project-dataset]");
  if (unlinkButton) {
    event.preventDefault();
    unlinkProjectDataset(unlinkButton.dataset.unlinkProjectDataset);
    return;
  }
  const row = event.target.closest("tr[data-resource-type]");
  if (!row || !state.dashboard) return;
  selectResource(row.dataset.resourceType, row.dataset.resourceId);
});

async function selectProject(projectId) {
  state.currentProjectId = projectId;
  state.activeView = "dashboard";
  state.details = {};
  state.datasetVersionTargets = {};
  state.trainingForm.versions = [];
  await refresh();
}

async function showProjects() {
  state.currentProjectId = null;
  state.activeView = "dashboard";
  state.details = {};
  state.datasetVersionTargets = {};
  state.trainingForm.versions = [];
  await refresh();
}

document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const runButton = event.target.closest("[data-jump-run]");
  if (runButton) {
    event.preventDefault();
    jumpToRun(runButton.dataset.jumpRun);
    return;
  }
  const datasetVersionButton = event.target.closest("[data-jump-dataset-version]");
  if (datasetVersionButton) {
    event.preventDefault();
    jumpToDatasetVersion(datasetVersionButton.dataset.jumpDatasetVersion);
    return;
  }
  const row = event.target.closest("tr[data-resource-type]");
  if (!row || !state.dashboard) return;
  event.preventDefault();
  selectResource(row.dataset.resourceType, row.dataset.resourceId);
});

document.addEventListener("submit", submitModelRegistration);
document.addEventListener("submit", submitDatasetMetadata);

$("#refreshButton").addEventListener("click", refresh);
$("#projectBackButton").addEventListener("click", showProjects);
$("#fullTestButton")?.addEventListener("click", runFullTest);
$("#emptyImportButton").addEventListener("click", runFullTest);
$("#newJobButton").addEventListener("click", openTrainingForm);
$("#cancelJobForm").addEventListener("click", closeTrainingForm);
$("#localeSelect").addEventListener("change", (event) => setLocale(event.target.value));
$("#jobTemplate").addEventListener("change", () => {
  renderDatasetOptions();
  renderParamInputs();
  renderJobFormStatus();
});
$("#jobForm").addEventListener("submit", submitTrainingJob);
state.locale = readInitialLocale();
renderStaticI18n();
bindNav();
refresh();
