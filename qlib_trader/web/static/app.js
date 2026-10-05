/* Qlib Studio. Local-only, no build step and no third-party frontend dependencies. */
"use strict";
(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) =>
    Array.from(root.querySelectorAll(selector));
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const icons = {
    grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
    workflow: "M4 4h6v6H4z M14 14h6v6h-6z M7 10v7h7 M10 7h7v7",
    cube: "m12 3 9 5v8l-9 5-9-5V8z M3 8l9 5 9-5 M12 13v8 M7.5 5.5l9 5",
    database:
      "M3 6c0-4 18-4 18 0s-18 4-18 0v12c0 4 18 4 18 0V6 M3 12c0 4 18 4 18 0",
    terminal: "M4 5h16v14H4z M7 9l3 3-3 3 M12 15h5",
    chart: "M4 4v16h16 M7 15l4-5 4 3 5-8",
    layers: "m12 3 10 5-10 5L2 8z M2 12l10 5 10-5 M2 16l10 5 10-5",
    arrow: "M4 12h16 M14 6l6 6-6 6",
    play: "m8 5 11 7-11 7z",
    refresh:
      "M20 7a9 9 0 0 0-15-2L2 8 M2 2v6h6 M4 17a9 9 0 0 0 15 2l3-3 M22 22v-6h-6",
    save: "M4 3h13l4 4v14H3V3z M7 3v6h10V3 M7 21v-8h10v8",
    download: "M12 3v12 M7 10l5 5 5-5 M4 16v5h16v-5",
    check: "m5 12 4 4L19 6",
    info: "M12 11v6 M12 7h.01 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
    clock: "M12 7v5l3 2 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
    external: "M14 3h7v7 M21 3l-11 11 M11 3H3v18h18v-8",
    code: "m8 7-5 5 5 5 M16 7l5 5-5 5 M14 4l-4 16",
    search: "M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
    menu: "M4 6h16 M4 12h16 M4 18h16",
    folder: "M3 6h7l2 3h9v12H3z",
    stop: "M6 6h12v12H6z",
    settings: "M4 7h16 M4 17h16 M8 4v6 M16 14v6",
  };
  const icon = (name) =>
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${icons[name] || icons.grid}"/></svg>`;
  const routes = {
    overview: ["研究概览", "grid"],
    workflow: ["工作流配置", "workflow"],
    models: ["模型目录", "cube"],
    data: ["数据与因子", "database"],
    jobs: ["任务与结果", "terminal"],
    experiments: ["实验对比", "chart"],
    capabilities: ["功能地图", "layers"],
  };
  const statusLabels = {
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
    interrupted: "已中断",
    ready: "已接入",
    external: "Python 扩展",
    unsupported: "暂不支持",
    missing: "缺少依赖",
  };
  const kindLabels = {
    pipeline: "完整工作流",
    train: "模型训练",
    backtest: "策略回测",
    inspect: "数据检查",
    features: "因子查询",
  };
  const state = {
    catalog: null,
    health: null,
    csrf: "",
    draft: null,
    jsonDraft: {},
    jobs: [],
    configs: [],
    experiments: [],
    selected: new Set(),
    route: "overview",
    jobId: null,
    job: null,
    jobTab: "results",
    logs: "",
    logOffset: 0,
    artifacts: [],
    dataStatus: null,
    dataError: "",
    dataChecked: false,
    dataSource: null,
    jobFilter: "all",
    lastYaml: "",
    validated: null,
    busy: new Set(),
    connected: true,
    query: {
      instruments: "SH600000",
      fields: "$close\n$volume",
      start_time: "2019-01-01",
      end_time: "2019-01-31",
    },
    polling: false,
    detailKey: 0,
  };
  const badge = (status, label) =>
    `<span class="badge ${esc(status === "external" ? "manual" : status)}">${status === "running" ? '<i class="dot"></i>' : ""}${esc(label || statusLabels[status] || status)}</span>`;
  const dateTime = (value) => {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? esc(value)
      : date.toLocaleString("zh-CN", {
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        });
  };
  const number = (value) =>
    typeof value === "number" && Number.isFinite(value)
      ? value.toLocaleString("zh-CN", { maximumFractionDigits: 4 })
      : "—";
  const percent = (value) =>
    typeof value === "number" && Number.isFinite(value)
      ? `${(value * 100).toFixed(2)}%`
      : "—";
  const metricFormat = (key, value) =>
    /annualized_return|max_drawdown|(?:^|\.)return$/.test(key)
      ? percent(value)
      : number(value);
  const bytes = (n) =>
    n >= 1048576
      ? `${(n / 1048576).toFixed(1)} MB`
      : n >= 1024
        ? `${(n / 1024).toFixed(1)} KB`
        : `${n || 0} B`;
  const deepModels = ["lstm", "gru", "alstm", "transformer"];
  const activeJobs = () =>
    state.jobs.filter((j) => ["queued", "running"].includes(j.status));
  const completedJobs = () =>
    state.jobs.filter((j) => j.status === "completed" && j.result?.recorder_id);
  const empty = (title, message, action = "", symbol = "chart") =>
    `<div class="empty"><div class="empty-icon">${icon(symbol)}</div><h3>${esc(title)}</h3><p>${esc(message)}</p>${action}</div>`;
  const notice = (message, type = "") =>
    `<div class="notice ${esc(type)}">${icon("info")}<div>${esc(message)}</div></div>`;
  const button = (label, action, type = "", symbol = "", extra = "") =>
    `<button type="button" class="button ${type}" data-action="${action}" ${extra}>${symbol ? icon(symbol) : ""}${esc(label)}</button>`;
  const heading = (
    title,
    subtitle,
    actions = "",
    eyebrow = "QLIB RESEARCH WORKSPACE",
  ) =>
    `<header class="page-heading"><div><span class="eyebrow">${esc(eyebrow)}</span><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div>${actions ? `<div class="actions">${actions}</div>` : ""}</header>`;
  const cardHead = (title, sub = "", right = "") =>
    `<div class="card-head"><div><h2>${esc(title)}</h2>${sub ? `<p>${esc(sub)}</p>` : ""}</div>${right}</div>`;
  function toast(message, type = "") {
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = message;
    $("#toasts").append(el);
    setTimeout(() => el.remove(), type === "error" ? 9000 : 4500);
  }
  function errorText(error) {
    if (Array.isArray(error))
      return error
        .map(
          (item) =>
            `${(item.loc || []).filter((v) => v !== "body").join(" · ")}${item.loc?.length ? "：" : ""}${item.msg || JSON.stringify(item)}`,
        )
        .join("\n");
    return typeof error === "string"
      ? error
      : error?.message || JSON.stringify(error);
  }
  async function api(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      headers["X-Console-Token"] = state.csrf;
    }
    const response = await fetch(`/api${path}`, {
      ...options,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    let data;
    try {
      data = await response.json();
    } catch (_) {
      throw new Error(`服务器返回了无法解析的响应 (${response.status})`);
    }
    if (!response.ok)
      throw new Error(
        errorText(data.detail || data.error || `请求失败 (${response.status})`),
      );
    return data;
  }
  function setDraft(config) {
    state.draft = clone(config);
    for (const key of ["model_kwargs", "handler_kwargs", "strategy_kwargs"])
      state.jsonDraft[key] = JSON.stringify(state.draft[key] || {}, null, 2);
    state.validated = null;
    state.lastYaml = "";
  }
  function formConfig() {
    const form = $("#workflow-form");
    if (form && !form.reportValidity())
      throw new Error("请先填写完整的有效配置。");
    const config = clone(state.draft);
    for (const key of ["model_kwargs", "handler_kwargs", "strategy_kwargs"]) {
      try {
        config[key] = JSON.parse(state.jsonDraft[key] || "{}");
      } catch (_) {
        throw new Error(
          `${{ model_kwargs: "模型", handler_kwargs: "数据处理", strategy_kwargs: "策略" }[key]}高级参数不是有效 JSON。`,
        );
      }
      if (
        !config[key] ||
        Array.isArray(config[key]) ||
        typeof config[key] !== "object"
      )
        throw new Error(
          '高级参数必须是 JSON 对象，例如 {"learning_rate": 0.05}。',
        );
    }
    return config;
  }
  function safeLink(url) {
    try {
      const u = new URL(url, location.origin);
      if (
        u.protocol === "https:" ||
        (u.origin === location.origin && u.pathname.startsWith("/api/"))
      )
        return esc(u.href);
    } catch (_) {}
    return "#";
  }
  function currentRoute() {
    const [route, id] = location.hash.replace(/^#/, "").split("/");
    state.route = routes[route] ? route : "overview";
    if (state.route === "jobs")
      state.jobId = id || state.jobId || state.jobs[0]?.id || null;
  }
  function navigate(route, id) {
    const hash = `#${route}${id ? `/${encodeURIComponent(id)}` : ""}`;
    if (location.hash === hash) renderView();
    else location.hash = hash;
  }
  function shell() {
    $("#app").innerHTML =
      `<div class="shell"><button class="mobile-overlay" aria-label="关闭导航" data-action="toggle-menu"></button><aside class="sidebar"><a class="brand" href="#overview" aria-label="Qlib Studio 首页"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span><span class="brand-name">Qlib <span>studio</span></span></a><div class="nav-label">Research console</div><nav aria-label="主导航">${Object.entries(
        routes,
      )
        .map(
          ([key, [label, symbol]], i) =>
            `${i === 6 ? '<div class="nav-label">Explore & extend</div>' : ""}<a href="#${key}" class="nav-item" data-nav="${key}">${icon(symbol)}<span>${label}</span>${key === "jobs" ? '<span class="count" id="nav-job-count">0</span>' : ""}</a>`,
        )
        .join(
          "",
        )}</nav><div class="sidebar-foot"><div class="local-tag"><span class="dot"></span>LOCAL WORKSPACE</div><p>研究在本机运行<br>数据与模型由你掌控</p></div></aside><div class="workspace"><header class="topbar"><div class="breadcrumb"><button class="icon-button menu-button" type="button" data-action="toggle-menu" aria-label="打开导航" aria-expanded="false">${icon("menu")}</button><span class="parent-crumb">工作空间</span><span class="parent-crumb">/</span><span id="breadcrumb-current"></span></div><div class="topbar-right"><span class="status-pill" id="connection-status"></span><button class="icon-button" type="button" data-action="refresh" aria-label="刷新工作空间" title="刷新工作空间">${icon("refresh")}</button></div></header><main id="main" class="main" tabindex="-1"></main></div></div>`;
    renderView();
  }
  function updateStatus() {
    const el = $("#connection-status");
    if (el)
      el.innerHTML = `<i class="dot ${state.connected ? "" : "error"}"></i>${state.connected ? "本地服务已连接" : "连接中断，正在重试"}`;
    const count = $("#nav-job-count");
    if (count) count.textContent = String(activeJobs().length);
  }
  function renderView() {
    if (!state.catalog) return;
    currentRoute();
    $$(".nav-item").forEach((el) => {
      const active = el.dataset.nav === state.route;
      el.classList.toggle("active", active);
      if (active) el.setAttribute("aria-current", "page");
      else el.removeAttribute("aria-current");
    });
    $("#breadcrumb-current").textContent = routes[state.route][0];
    updateStatus();
    const views = {
      overview: overviewView,
      workflow: workflowView,
      models: modelsView,
      data: dataView,
      jobs: jobsView,
      experiments: experimentsView,
      capabilities: capabilitiesView,
    };
    $("#main").innerHTML = views[state.route]();
    $(".shell").classList.remove("menu-open");
    $(".menu-button").setAttribute("aria-expanded", "false");
    document.title = `${routes[state.route][0]} · Qlib Studio`;
    if (state.route === "jobs" && state.jobId) loadJob(state.jobId, true);
  }
  function healthContent() {
    const h = state.health;
    if (!h) return notice("无法获取环境信息，请刷新重试。", "warning");
    const deps = Object.entries(h.dependencies || {});
    return `<div class="health-row"><span class="label">Qlib 引擎</span><span class="value">${badge(h.qlib_available ? "ready" : "missing", h.qlib_available ? "已就绪" : "未就绪")}</span></div><div class="health-row"><span class="label">运行方式</span><span class="value">本地进程 · 串行队列</span></div><div class="health-row"><span class="label">可用模型依赖</span><span class="value mono">${Object.values(state.catalog.models).filter((m) => m.available).length} / ${Object.keys(state.catalog.models).length}</span></div><div class="health-row"><span class="label">控制台版本</span><span class="value mono">${esc(h.version || "—")}</span></div>${h.qlib_available ? "" : `<div class="health-note">Qlib 尚未加载。仍可编辑、校验和导出配置；真实训练需要完整依赖与本地数据。${h.qlib_error ? `<br><span class="code-inline">${esc(h.qlib_error)}</span>` : ""}</div>`}${deps.length ? `<details><summary>查看依赖状态</summary><div style="margin-top:12px">${deps.map(([name, value]) => `<div class="health-row"><span class="label mono">${esc(name)}</span><span class="value">${typeof value === "object" ? esc(JSON.stringify(value)) : value === true ? "已安装" : value === false ? "未安装" : esc(value)}</span></div>`).join("")}</div></details>` : ""}`;
  }
  function workflowStrip() {
    return `<div class="workflow-strip">${[
      ["database", "数据准备", "Local data"],
      ["layers", "特征工程", "Alpha factors"],
      ["cube", "模型训练", "Prediction"],
      ["settings", "策略回测", "Backtesting"],
      ["chart", "结果分析", "Evaluation"],
    ]
      .map(
        ([i, t, s]) =>
          `<div class="flow-node"><div class="flow-icon">${icon(i)}</div><h3>${t}</h3><small>${s}</small></div>`,
      )
      .join("")}</div>`;
  }
  function overviewView() {
    const completed = state.jobs.filter((j) => j.status === "completed").length;
    const templates = state.catalog.templates.slice(0, 3);
    return `${heading("把研究想法，变成可复现的实验。", "从数据与因子到预测和回测，在一个工作台里完成你的 Qlib 研究。", button("新建工作流", "new-workflow", "primary", "play"), "YOUR QUANTITATIVE WORKSPACE")}<div class="grid-4"><article class="card stat-card"><div class="stat-label">实验任务${icon("terminal")}</div><div class="stat-value">${state.jobs.length}<span class="muted" style="font-size:13px;margin-left:8px">次</span></div><div class="stat-foot"><span class="text-green">${completed} 已完成</span> · ${activeJobs().length} 正在处理</div></article><article class="card stat-card"><div class="stat-label">研究配置${icon("folder")}</div><div class="stat-value">${state.configs.length}<span class="muted" style="font-size:13px;margin-left:8px">份</span></div><div class="stat-foot">本地保存 · 随时加载与复用</div></article><article class="card stat-card"><div class="stat-label">内置模型${icon("cube")}</div><div class="stat-value">${Object.keys(state.catalog.models).length}<span class="muted" style="font-size:13px;margin-left:8px">种</span></div><div class="stat-foot">树模型 / 线性 / 深度学习</div></article><article class="card stat-card"><div class="stat-label">因子处理器${icon("layers")}</div><div class="stat-value">${Object.keys(state.catalog.handlers).length}<span class="muted" style="font-size:13px;margin-left:8px">套</span></div><div class="stat-foot">Alpha158 与 Alpha360</div></article></div><div class="overview-layout" style="margin-top:20px"><article class="card hero"><span class="eyebrow">END-TO-END RESEARCH</span><h2>一条工作流，串起整个研究过程</h2><p>选择股票池、因子和模型，设定严格分离的训练 / 验证 / 测试区间。每次运行保留独立日志、配置和结果，方便比较与复现。</p><div class="actions">${button("配置第一个实验", "goto-workflow", "primary", "arrow")}${button("检查本地数据", "goto-data", "", "database")}</div>${workflowStrip()}</article><article class="card">${cardHead("运行环境", "先确认依赖，再开始研究", icon("terminal"))}<div class="card-body">${healthContent()}</div></article></div><section><div class="section-title"><h2>从研究模板开始</h2><button class="text-button" data-action="goto-models">探索全部模型 ${icon("arrow")}</button></div><div class="grid-3">${templates.map((t, i) => `<button type="button" class="card template-card" data-action="template" data-id="${esc(t.id)}"><div class="template-top"><div class="template-icon">${icon(["chart", "cube", "settings"][i])}</div><span class="tag ${i === 0 ? "lime" : ""}">${i === 0 ? "START HERE" : i === 1 ? "DEEP LEARNING" : "LOW TURNOVER"}</span></div><h3>${esc(t.name)}</h3><p>${esc(t.description)}</p><footer><span>预填参数 · 可自由调整</span>${icon("arrow")}</footer></button>`).join("")}</div></section><section><div class="section-title"><h2>最近的研究任务</h2><button class="text-button" data-action="goto-jobs">查看全部 ${icon("arrow")}</button></div><div class="card">${state.jobs.length ? jobsTable(state.jobs.slice(0, 5)) : empty("研究记录，等待你的第一步", "这里将展示真实任务的状态和结果。完成一次实验后，开始积累你的研究记录。", button("创建工作流", "goto-workflow", "small", "", ""), "terminal")}</div></section>${footer()}`;
  }
  const footer = () =>
    `<footer class="footer-note"><span>QLIB STUDIO / 本地量化研究工作台</span><span>回测仅用于研究，不代表未来收益 · 不连接券商、不执行交易</span></footer>`;
  function optionEntries(entries, selected) {
    return Object.entries(entries || {})
      .map(
        ([key, val]) =>
          `<option value="${esc(key)}" ${key === selected ? "selected" : ""}>${esc(val.name || key)}</option>`,
      )
      .join("");
  }
  function input(name, label, type = "text", hint = "", extra = "") {
    return `<div class="field"><label for="field-${name}">${label}</label><input id="field-${name}" name="${name}" type="${type}" value="${esc(state.draft[name])}" ${extra} required>${hint ? `<span class="hint">${hint}</span>` : ""}</div>`;
  }
  function select(name, label, entries, hint = "") {
    return `<div class="field"><label for="field-${name}">${label}</label><select id="field-${name}" name="${name}">${optionEntries(entries, state.draft[name])}</select>${hint ? `<span class="hint">${hint}</span>` : ""}</div>`;
  }
  function advanced(name, label, hint) {
    return `<div class="field full"><label for="field-${name}">${label}</label><textarea id="field-${name}" name="${name}" spellcheck="false" rows="4" aria-describedby="hint-${name}">${esc(state.jsonDraft[name])}</textarea><span class="hint" id="hint-${name}">${hint}</span></div>`;
  }
  function formSection(n, title, desc, content) {
    return `<section class="card form-panel"><div class="form-section-heading"><span class="step-number">${n}</span><div><h2>${title}</h2><p>${desc}</p></div></div>${content}</section>`;
  }
  function workflowView() {
    const c = state.draft;
    return `${heading("设计你的研究工作流", "配置不会自动执行。先校验与预览，再将任务送入本地运行队列。", button("保存配置", "save-config", "", "save"))}<div class="form-layout"><form id="workflow-form" class="stack">${formSection("01", "研究与数据", "选择本地数据源、区域和证券池。", `<div class="fields">${input("name", "研究名称", "text", "", 'maxlength="80"')}${select("region", "市场区域", state.catalog.regions)}<div class="field full"><label for="field-provider_uri">本地 Qlib 数据目录</label><input id="field-provider_uri" name="provider_uri" value="${esc(c.provider_uri)}" required maxlength="1024"><span class="hint">填写已准备好的本地目录。控制台不会自动下载或覆盖数据。</span></div>${input("market", "证券池 / Market", "text", "例如 csi300、csi500、sp500")}${input("benchmark", "回测基准 / Benchmark", "text", "例如 SH000300、^gspc")}</div>`)}${formSection("02", "特征与模型", "预设提供基础参数，高级配置支持安全的 JSON 覆盖。", `<div class="fields">${select("handler", "因子处理器", state.catalog.handlers)}${select("model", "预测模型", state.catalog.models)}</div><div id="model-guidance" style="margin-top:15px">${modelGuidance()}</div><details><summary>高级参数 · 模型与数据处理器</summary><div class="fields">${advanced("model_kwargs", "模型参数覆盖", '例如 {"learning_rate": 0.05, "num_threads": 4}。仅允许已支持的参数；不执行 Python。')}${advanced("handler_kwargs", "数据处理器参数覆盖", '支持 label 表达式列表和 drop_raw 布尔值。例如 {"label": ["Ref($close, -2) / Ref($close, -1) - 1"]}。')}</div></details>`)}${formSection(
      "03",
      "时间划分",
      "严格分离训练、验证、测试，降低数据泄漏风险。",
      `<div class="fields" style="margin-bottom:19px">${select("time_range", "时间范围预设", { ...state.catalog.times, custom: { name: "自定义时间范围" } })}</div><div class="segment-labels"><span>数据段</span><span>开始日期</span><span></span><span>结束日期</span></div>${[
        ["train", "训练集"],
        ["valid", "验证集"],
        ["test", "测试集"],
      ]
        .map(
          ([key, label]) =>
            `<div class="segment-row"><span class="segment-name"><i class="segment-dot ${key}"></i>${label}</span><div class="field"><label class="sr-only" for="field-${key}_start">${label}开始日期</label><input id="field-${key}_start" name="${key}_start" type="date" value="${esc(c[`${key}_start`])}" required></div><span class="muted" style="text-align:center">→</span><div class="field"><label class="sr-only" for="field-${key}_end">${label}结束日期</label><input id="field-${key}_end" name="${key}_end" type="date" value="${esc(c[`${key}_end`])}" required></div></div>`,
        )
        .join(
          "",
        )}<div class="segment-timeline" aria-hidden="true"><span style="flex:6;background:var(--accent)"></span><span style="flex:2;background:var(--blue)"></span><span style="flex:3;background:var(--green)"></span></div><div class="narrow-note">示意图；实际区间以日期输入为准。训练结束 &lt; 验证开始，验证结束 &lt; 测试开始。</div>`,
    )}${formSection("04", "策略与交易成本", "研究设置，不会创建真实订单。所有费率均使用小数。", `<div class="fields">${select("strategy", "选股策略", state.catalog.strategies)}${input("account", "初始资金（所选市场计价单位）", "number", "", 'min="0.01" max="1000000000000" step="any"')}${input("topk", "持仓数量 / Top K", "number", "", 'min="1" max="10000" step="1"')}${input("n_drop", "每期淘汰数量 / N Drop", "number", "", 'min="0" max="10000" step="1"')}</div><div class="fields three" style="margin-top:17px">${input("open_cost", "买入费率", "number", "0.0005 = 0.05%", 'min="0" max="0.1" step="0.0001"')}${input("close_cost", "卖出费率", "number", "0.0015 = 0.15%", 'min="0" max="0.1" step="0.0001"')}${input("min_cost", "单笔最低费用", "number", "", 'min="0" max="1000000" step="any"')}</div><div id="strategy-guidance" style="margin-top:14px">${strategyGuidance()}</div><details><summary>高级参数 · 策略</summary><div class="fields">${advanced("strategy_kwargs", "策略参数覆盖", '例如 {"risk_degree": 0.95, "hold_thresh": 1}。持仓和淘汰数量请在上方设置。')}</div></details>`)}<div id="validation-result" class="validation-result" aria-live="polite"></div><div class="workflow-toolbar"><span>可复现配置<br>独立实验记录</span><div class="actions">${button("校验配置", "validate", "", "check")}${button("预览 YAML", "preview-yaml", "", "code")}${button("导出 YAML", "export-yaml", "", "download")}</div></div></form><aside class="form-side"><article class="card">${cardHead("实验摘要", "YOUR NEXT EXPERIMENT")}<div class="card-body"><div id="workflow-summary">${summaryContent()}</div>${button("运行完整工作流", "run-pipeline", "primary run-button", "play")}<div class="run-options">${button("仅训练", "run-train", "small")}${button("仅回测", "run-backtest", "small")}</div><div class="field" style="margin-top:16px"><label for="source-job">回测使用已完成实验的预测</label><select id="source-job"><option value="">选择来源实验</option>${completedJobs()
      .filter((j) => ["train", "pipeline"].includes(j.kind))
      .map(
        (j) =>
          `<option value="${esc(j.id)}">${esc(j.name)} · ${dateTime(j.created_at)}</option>`,
      )
      .join(
        "",
      )}</select><span class="hint">选择来源后自动同步数据源、模型、因子与全部研究区间，保留当前策略和费用。来源预测保持不变。</span></div></div></article><article class="card">${cardHead("已保存配置", `${state.configs.length} 份研究设置`)}<div class="card-body">${savedConfigs()}</div></article>${notice("任务在独立子进程中串行执行。首次训练可能较慢，请在「任务与结果」查看实时日志。")}</aside></div>${footer()}`;
  }
  function modelGuidance() {
    const m = state.catalog.models[state.draft.model];
    const notes = [];
    if (m?.available === false)
      notes.push(
        `当前缺少 ${m.dependency} 依赖；可先编辑和导出配置，训练前需要安装。`,
      );
    if (deepModels.includes(state.draft.model))
      notes.push(
        state.draft.handler === "alpha360"
          ? "Alpha360 使用 6 维特征 × 60 步时序窗口；默认在 CPU 上运行。"
          : "Alpha158 在此模型中作为单步特征。要使用 60 步时序窗口，请选择 Alpha360。",
      );
    return notes
      .map((n) => notice(n, m?.available === false ? "warning" : ""))
      .join("");
  }
  function strategyGuidance() {
    return state.draft.strategy === "topk_weighted"
      ? notice(
          "此预设仍使用 TopkDropoutStrategy，只改变持仓与换手参数，并非独立的加权策略。",
          "warning",
        )
      : "";
  }
  function summaryContent() {
    const c = state.draft;
    return `<span class="eyebrow">MODEL / ${esc(c.handler.toUpperCase())}</span><div class="summary-model">${esc(c.model === "lightgbm" ? "LightGBM" : c.model === "xgboost" ? "XGBoost" : c.model.toUpperCase())}</div>${[
      ["股票池", `${c.market} · ${c.region.toUpperCase()}`],
      ["策略", `${c.topk} 持仓 / ${c.n_drop} 淘汰`],
      ["测试区间", `${c.test_start} → ${c.test_end}`],
      ["基准", c.benchmark],
      [
        "买入 / 卖出费用",
        `${percent(Number(c.open_cost))} / ${percent(Number(c.close_cost))}`,
      ],
    ]
      .map(
        ([k, v]) =>
          `<div class="summary-item"><span>${esc(k)}</span><span>${esc(v)}</span></div>`,
      )
      .join("")}`;
  }
  function savedConfigs() {
    return state.configs.length
      ? `<div class="save-list">${state.configs
          .slice(0, 20)
          .map(
            (c) =>
              `<div class="save-item"><div><p>${esc(c.name)}</p><small>${dateTime(c.updated_at)}</small></div>${button("加载", "load-config", "small", "", 'data-id="' + esc(c.id) + '"')}</div>`,
          )
          .join("")}</div>`
      : '<p class="narrow-note">暂未保存配置。保存后可在这里重新加载。</p>';
  }
  function modelsView() {
    return `${heading("模型目录", "从基线到时序深度学习，选择与你的因子和研究目标匹配的模型。", button("返回工作流", "goto-workflow", "", "arrow"))}<div class="toolbar"><p>模型可用性反映当前 Python 环境的依赖检查，实际运行仍以任务日志为准。</p><span class="tag">${Object.keys(state.catalog.models).length} BUILT-IN MODELS</span></div><div class="grid-3">${Object.entries(
      state.catalog.models,
    )
      .map(
        ([key, m]) =>
          `<article class="card model-card ${m.available ? "" : "unavailable"}"><div class="card-body"><div class="template-top"><div class="template-icon">${icon(deepModels.includes(key) ? "layers" : "cube")}</div>${badge(m.available ? "ready" : "missing", m.available ? "依赖已安装" : `需 ${m.dependency}`)}</div><h2>${esc(m.name)}</h2><p>${esc(m.description)}</p><div class="model-params"><span class="tag">${deepModels.includes(key) ? "深度学习" : key === "linear" ? "线性基线" : "梯度提升"}</span><span class="tag">${deepModels.includes(key) ? "推荐 Alpha360" : "Alpha158 / Alpha360"}</span></div><details><summary>查看预设参数</summary><div class="param-text mono">${
            Object.keys(m.kwargs || {}).length
              ? Object.entries(m.kwargs)
                  .map(([k, v]) => `${esc(k)}: ${esc(JSON.stringify(v))}`)
                  .join("<br>")
              : "使用模型默认参数"
          }${deepModels.includes(key) ? '<br><span class="text-orange">控制台会根据处理器适配 d_feat；GPU 默认 -1（CPU）。</span>' : ""}</div></details></div><div class="card-footer"><span class="model-id mono">${esc(m.class || key)}</span>${button("用于研究", "select-model", "small", "", 'data-id="' + esc(key) + '"')}</div></article>`,
      )
      .join(
        "",
      )}</div><div style="margin-top:20px">${notice("更广泛的 Qlib 能力（强化学习、高频执行、在线学习）需要专门的 Python 工作流。请在功能地图查看真实的支持范围。")}</div>${footer()}`;
  }
  function dataView() {
    return `${heading("数据与因子", "检查本地 Qlib 数据结构，用证券代码和数值表达式查询真实数据。", button("刷新数据状态", "data-status", "", "refresh"))}<div class="grid-2"><section class="card">${cardHead("本地数据源", "与当前工作流共用区域和目录")}<div class="card-body"><div class="fields"><div class="field"><label for="field-data-region">市场区域</label><select id="field-data-region" name="data-region">${optionEntries(state.catalog.regions, state.draft.region)}</select></div><div class="field"><label for="data-provider">Qlib 数据目录</label><input id="data-provider" name="data-provider" value="${esc(state.draft.provider_uri)}" placeholder="~/.qlib/qlib_data/cn_data"></div></div><div class="actions" style="margin-top:17px">${button("检查目录", "data-status", "primary", "search")}${button("运行数据检查", "run-inspect", "", "terminal")}</div><div id="data-status-result" style="margin-top:20px">${dataStatusContent()}</div></div></section><section class="card">${cardHead("因子与行情查询", "查询作为独立后台任务执行")}<form id="query-form" class="card-body"><div class="fields"><div class="field full"><label for="query-instruments">证券代码（英文逗号或换行分隔）</label><input id="query-instruments" name="query-instruments" value="${esc(state.query.instruments)}" required placeholder="SH600000, SH600519"><span class="hint">最多 20 个证券代码；请使用当前数据集里的代码。</span></div><div class="field full"><label for="query-fields">字段 / 因子表达式（每行一个）</label><textarea id="query-fields" name="query-fields" rows="3" required spellcheck="false">${esc(state.query.fields)}</textarea><span class="hint">例如 $close、$volume、Mean($close, 5)；仅允许内置数值表达式，最多 10 个。</span></div><div class="field"><label for="query-start_time">开始日期</label><input id="query-start_time" name="query-start_time" type="date" value="${esc(state.query.start_time)}" required></div><div class="field"><label for="query-end_time">结束日期</label><input id="query-end_time" name="query-end_time" type="date" value="${esc(state.query.end_time)}" required></div></div><div class="actions" style="margin-top:20px">${button("提交查询", "run-features", "primary", "search")}</div></form></section></div><div style="margin-top:20px">${notice("结构检查只读取日历、证券和特征文件的元信息，不保证内容完整。数据采集与增量更新请先使用仓库的数据脚本；控制台不会隐式下载数据或覆盖你的目录。")}</div>${footer()}`;
  }
  function dataStatusContent() {
    if (state.dataError) return notice(state.dataError, "error");
    if (!state.dataChecked)
      return empty(
        "尚未检查数据目录",
        "确认区域与路径后点击「检查目录」。这里不会展示虚构的行情或交易日。",
        "",
        "database",
      );
    const d = state.dataStatus;
    return `<div class="actions" style="justify-content:space-between">${badge(d.ready ? "ready" : "missing", d.ready ? "数据结构就绪" : d.exists ? "目录待完善" : "目录不存在")}<span class="narrow-note">${esc(d.start_date || "—")} → ${esc(d.end_date || "—")}</span></div><div class="data-status-grid">${[
      ["交易日", d.calendar_count],
      ["证券", d.instrument_count],
      ["特征证券目录", d.feature_count],
      ["区域", state.dataSource?.region?.toUpperCase()],
    ]
      .map(
        ([label, value]) =>
          `<div class="data-stat"><span>${label}</span><strong>${typeof value === "number" ? number(value) : esc(value || "—")}</strong></div>`,
      )
      .join(
        "",
      )}</div><p class="code-inline" style="margin-top:15px">${esc(d.provider_uri)}</p>${(d.warnings || []).map((w) => `<div style="margin-top:12px">${notice(w, "warning")}</div>`).join("")}`;
  }
  function jobsTable(jobs) {
    return `<div class="table-wrap"><table><thead><tr><th>研究名称</th><th>类型 / 模型</th><th>状态</th><th>创建时间</th><th><span class="sr-only">操作</span></th></tr></thead><tbody>${jobs.map((j) => `<tr><td><span class="job-name">${esc(j.name)}</span><small class="mono">${esc(j.id.slice(0, 8))}</small></td><td>${esc(kindLabels[j.kind] || j.kind)}<small>${esc(j.config?.model || "—")} · ${esc(j.config?.market || "—")}</small></td><td>${badge(j.status)}</td><td class="muted">${dateTime(j.created_at)}</td><td><button class="table-action" data-action="open-job" data-id="${esc(j.id)}">查看 →</button></td></tr>`).join("")}</tbody></table></div>`;
  }
  function jobListContent() {
    const jobs = state.jobs.filter(
      (j) => state.jobFilter === "all" || j.status === state.jobFilter,
    );
    return jobs.length
      ? jobs
          .map(
            (j) =>
              `<button type="button" class="job-list-item ${j.id === state.jobId ? "selected" : ""}" data-action="open-job" data-id="${esc(j.id)}"><div class="row"><h3>${esc(j.name)}</h3>${badge(j.status)}</div><small>${esc(kindLabels[j.kind] || j.kind)} · ${esc(j.config?.model || "—")}</small><small class="mono">${dateTime(j.created_at)} <span style="float:right">${esc(j.id.slice(0, 8))}</span></small></button>`,
          )
          .join("")
      : empty(
          "暂无匹配任务",
          "换一个状态筛选，或创建你的第一个研究任务。",
          "",
          "terminal",
        );
  }
  function jobsView() {
    return `${heading("任务与结果", "任务按顺序在独立进程中执行；日志、配置与真实结果保存在本地。", button("新建研究", "goto-workflow", "primary", "play"))}<div class="toolbar"><p><span id="job-total">${state.jobs.length}</span> 个任务 · <span id="job-active">${activeJobs().length}</span> 个等待或运行中 · 每 3 秒自动刷新</p><div class="actions"><label class="sr-only" for="job-filter">按状态筛选</label><select id="job-filter" class="filter-select"><option value="all">全部状态</option>${Object.entries(
      statusLabels,
    )
      .filter(([k]) =>
        [
          "queued",
          "running",
          "completed",
          "failed",
          "cancelled",
          "interrupted",
        ].includes(k),
      )
      .map(
        ([k, v]) =>
          `<option value="${k}" ${state.jobFilter === k ? "selected" : ""}>${v}</option>`,
      )
      .join(
        "",
      )}</select>${button("刷新", "refresh", "small", "refresh")}</div></div><div class="job-layout"><section class="card job-list" id="job-list" aria-label="任务列表">${jobListContent()}</section><section class="card job-details" id="job-details" aria-label="任务详情">${state.jobId ? '<div class="loading-inline"><span class="spinner"></span>正在读取任务…</div>' : empty("选择任务查看详情", "运行任务后，可以在这里查看日志、真实指标、收益曲线与导出文件。", button("配置工作流", "goto-workflow", "small"), "terminal")}</section></div>${footer()}`;
  }
  function jobDetailContent() {
    const j = state.job;
    if (!j)
      return empty(
        "没有可显示的任务",
        "请从左侧选择一个任务。",
        "",
        "terminal",
      );
    return `<div class="detail-heading"><div class="row"><h2>${esc(j.name)}</h2>${badge(j.status)}</div><div class="detail-metadata"><span>${esc(kindLabels[j.kind] || j.kind)}</span><span class="mono">${esc(j.id.slice(0, 12))}</span><span>创建于 ${dateTime(j.created_at)}</span></div>${["running", "queued"].includes(j.status) ? `<div class="actions" style="margin-top:15px">${button("取消任务", "cancel-job", "danger small", "stop", 'data-id="' + esc(j.id) + '"')}<span class="narrow-note">取消会终止此任务；已有日志将保留。</span></div>` : ""}${j.error ? `<div style="margin-top:14px">${notice(j.error, "error")}</div>` : ""}</div><div class="tab-bar" role="tablist" aria-label="任务详情视图">${[
      ["results", "研究结果"],
      ["logs", "运行日志"],
      ["artifacts", "导出文件"],
      ["config", "运行配置"],
    ]
      .map(
        ([id, label]) =>
          `<button type="button" role="tab" id="tab-${id}" aria-selected="${state.jobTab === id}" aria-controls="job-tab-panel" class="tab ${state.jobTab === id ? "active" : ""}" data-action="job-tab" data-tab="${id}">${label}</button>`,
      )
      .join(
        "",
      )}</div><div class="card-body" id="job-tab-panel" role="tabpanel" aria-labelledby="tab-${state.jobTab}">${jobTabContent()}</div>`;
  }
  function jobTabContent() {
    const j = state.job;
    if (!j) return "";
    if (state.jobTab === "logs")
      return `<div class="log-heading"><span>标准输出与错误日志 · 自动刷新</span><button class="text-button" data-action="copy-logs">复制日志</button></div><pre class="log-panel" id="log-output" tabindex="0" aria-label="运行日志">${esc(state.logs || (["queued", "running"].includes(j.status) ? "等待进程输出…" : "此任务没有日志输出。"))}</pre>`;
    if (state.jobTab === "config")
      return `<div class="actions" style="margin-bottom:15px">${button("加载到工作流", "use-job-config", "small", "workflow")}</div><pre class="config-pre">${esc(JSON.stringify(j.config, null, 2))}</pre>`;
    if (state.jobTab === "artifacts")
      return state.artifacts.length
        ? `<div class="artifact-list">${state.artifacts.map((a) => `<div class="artifact"><span>${esc(a.name)}<br><small>${bytes(a.size)}</small></span><a href="${safeLink(a.url)}" download>${icon("download")} 下载</a></div>`).join("")}</div>`
        : empty(
            "尚无可导出的文件",
            "任务完成后，这里会列出可下载的 CSV、JSON、YAML 或文本文件。",
            "",
            "folder",
          );
    return resultsContent(j);
  }
  function resultsContent(j) {
    if (!j.result)
      return empty(
        j.status === "failed"
          ? "任务未产生有效结果"
          : ["running", "queued"].includes(j.status)
            ? "真实结果正在生成"
            : j.status === "cancelled"
              ? "任务已取消"
              : "暂无研究结果",
        j.status === "failed"
          ? "查看运行日志定位具体原因，再调整配置或环境重新运行。"
          : ["running", "queued"].includes(j.status)
            ? "训练、预测与回测需要时间。可以切换到运行日志查看当前进度。"
            : "只有任务实际输出的数据会出现在这里。",
        button("查看日志", "job-tab", "small", "", 'data-tab="logs"'),
        "chart",
      );
    const r = j.result;
    const metrics = Object.entries(r.metrics || {}).filter(
      ([, v]) => typeof v === "number" && Number.isFinite(v),
    );
    return `${r.recorder_id ? `<p class="narrow-note mono" style="margin-bottom:15px">Recorder ${esc(r.recorder_id)}</p>` : ""}${
      metrics.length
        ? `<div class="metrics-grid">${metrics
            .slice(0, 12)
            .map(
              ([k, v]) =>
                `<div class="metric-box"><div class="metric-key">${esc(k)}</div><div class="metric-value">${metricFormat(k, v)}</div></div>`,
            )
            .join(
              "",
            )}</div>${metrics.length > 12 ? `<details><summary>全部 ${metrics.length} 项指标</summary><div class="table-wrap" style="margin-top:10px"><table><tbody>${metrics.map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td>${metricFormat(k, v)}</td></tr>`).join("")}</tbody></table></div></details>` : ""}`
        : ""
    }${
      Array.isArray(r.series) && r.series.length
        ? `<div class="result-section"><h3>累计收益表现</h3>${seriesChart(
            r.series,
            [
              ["return", "策略收益", "#d8f36a"],
              ["benchmark", "基准收益", "#8eaefc"],
              ["excess", "超额收益", "#69d5ad"],
            ],
          )}</div>${r.series.some((p) => typeof p.drawdown === "number") ? `<div class="result-section"><h3>回撤曲线</h3>${seriesChart(r.series, [["drawdown", "回撤", "#f8bd77"]])}</div>` : ""}`
        : ["pipeline", "backtest"].includes(j.kind)
          ? `<div class="result-section"><h3>累计收益表现</h3><div class="chart-empty">此任务没有输出可绘制的收益序列。请查看指标与运行日志。</div></div>`
          : ""
    }${r.preview ? `<div class="result-section"><h3>数据预览</h3>${previewTable(r.preview)}</div>` : ""}${r.summary && Object.keys(r.summary).length ? `<div class="result-section"><h3>运行摘要</h3><pre class="config-pre">${esc(JSON.stringify(r.summary, null, 2))}</pre></div>` : ""}${!metrics.length && !r.preview && !r.summary && !r.series?.length ? notice("任务已完成，但没有可展示的数值指标。请查看导出文件与日志。") : ""}<div class="result-section"><p class="narrow-note">以上数据均来自本次任务输出。历史回测不构成投资建议，也不保证未来收益。</p></div>`;
  }
  function seriesChart(series, defs) {
    const values = defs.flatMap(([key]) =>
      series
        .map((p) => p[key])
        .filter((v) => typeof v === "number" && Number.isFinite(v)),
    );
    if (!values.length)
      return '<div class="chart-empty">没有可用的数值序列</div>';
    let lo = values.reduce((min, value) => Math.min(min, value), 0),
      hi = values.reduce((max, value) => Math.max(max, value), 0);
    if (hi === lo) {
      lo -= 0.01;
      hi += 0.01;
    }
    const pad = (hi - lo) * 0.1;
    lo -= pad;
    hi += pad;
    const w = 720,
      h = 245,
      left = 53,
      right = 15,
      top = 15,
      bottom = 34;
    const x = (i) =>
      left + ((w - left - right) * i) / Math.max(1, series.length - 1);
    const y = (v) => top + ((hi - v) / (hi - lo)) * (h - top - bottom);
    const grid = Array.from({ length: 5 }, (_, i) => {
      const v = lo + ((hi - lo) * i) / 4;
      return `<line class="gridline" x1="${left}" x2="${w - right}" y1="${y(v)}" y2="${y(v)}"/><text text-anchor="end" x="${left - 10}" y="${y(v) + 3}">${(v * 100).toFixed(1)}%</text>`;
    }).join("");
    const lines = defs
      .map(([key, label, color]) => {
        let started = false;
        let path = "";
        series.forEach((p, i) => {
          if (typeof p[key] !== "number" || !Number.isFinite(p[key])) {
            started = false;
            return;
          }
          path += `${started ? "L" : "M"}${x(i).toFixed(2)},${y(p[key]).toFixed(2)} `;
          started = true;
        });
        return `<path d="${path}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"><title>${esc(label)}</title></path>`;
      })
      .join("");
    const ticks = [
      0,
      Math.floor((series.length - 1) / 2),
      series.length - 1,
    ].filter((v, i, a) => a.indexOf(v) === i);
    return `<div class="chart-legend">${defs.map(([, label, color]) => `<span><i style="background:${color}"></i>${esc(label)}</span>`).join("")}</div><div class="chart"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="真实任务输出的${esc(defs.map((d) => d[1]).join("、"))}曲线"><title>${esc(defs.map((d) => d[1]).join(" / "))}，${esc(series[0]?.date)} 至 ${esc(series[series.length - 1]?.date)}</title>${grid}${lines}${ticks.map((i, k) => `<text x="${x(i)}" y="${h - 8}" text-anchor="${k === 0 ? "start" : k === ticks.length - 1 ? "end" : "middle"}">${esc(String(series[i]?.date || "").slice(0, 10))}</text>`).join("")}</svg></div><p class="chart-footer">收益为扣除成本后的日收益算术累加（非复利净值），基准同口径；回撤为累计收益较前高的下降，纵轴为百分点 · ${series.length} 个时间点</p>`;
  }
  function previewTable(preview) {
    const rows = preview.rows || [];
    const cols = preview.columns?.length
      ? preview.columns
      : Object.keys(rows[0] || {});
    if (!rows.length)
      return notice(
        "此查询没有返回数据。请检查证券代码、时间范围与本地数据。",
        "warning",
      );
    return `<div class="table-wrap"><table><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows
      .slice(0, 30)
      .map(
        (row) =>
          `<tr>${cols
            .map((c, i) => {
              const v = Array.isArray(row) ? row[i] : row[c];
              return `<td class="mono">${v === null || v === undefined ? "—" : typeof v === "number" ? number(v) : esc(typeof v === "object" ? JSON.stringify(v) : v)}</td>`;
            })
            .join("")}</tr>`,
      )
      .join(
        "",
      )}</tbody></table></div><p class="narrow-note" style="margin-top:9px">展示 ${Math.min(30, rows.length)} 行预览；完整输出请查看导出文件。</p>`;
  }
  function experimentsView() {
    const experiments = state.experiments;
    const selected = experiments.filter((j) => state.selected.has(j.id));
    return `${heading("实验对比", "挑选已完成的实验，对比模型与实际输出的指标。", button("新建实验", "goto-workflow", "primary", "play"))}${notice("这里只展示本控制台创建、并成功生成 recorder 的实验，不扫描或导入其他 MLflow / Qlib 实验库。")}<div class="card" style="margin-top:20px">${experiments.length ? `<div class="table-wrap"><table><thead><tr><th><span class="sr-only">选择实验</span></th><th>实验</th><th>模型 / 因子</th><th>测试区间</th><th>创建时间</th><th>结果</th></tr></thead><tbody>${experiments.map((j) => `<tr><td><input type="checkbox" class="compare-select" data-experiment="${esc(j.id)}" ${state.selected.has(j.id) ? "checked" : ""} aria-label="选择实验 ${esc(j.name)}"></td><td><span class="job-name">${esc(j.name)}</span><small class="mono">${esc(j.id.slice(0, 8))}</small></td><td>${esc(j.config?.model)}<small>${esc(j.config?.handler)}</small></td><td class="muted">${esc(j.config?.test_start)}<small>至 ${esc(j.config?.test_end)}</small></td><td class="muted">${dateTime(j.created_at)}</td><td><button class="table-action" data-action="open-job" data-id="${esc(j.id)}">查看 →</button></td></tr>`).join("")}</tbody></table></div>` : empty("还没有可以比较的实验", "成功完成模型训练或完整工作流后，在这里选择至少两个实验。", button("开始研究", "goto-workflow", "small"), "chart")}</div><div id="comparison">${comparisonContent(selected)}</div>${footer()}`;
  }
  function comparisonContent(selected) {
    if (!selected.length) return "";
    if (selected.length === 1)
      return `<div style="margin-top:18px">${notice("已选择 1 个实验，再选择至少 1 个即可比较。")}</div>`;
    const keys = Array.from(
      new Set(selected.flatMap((j) => Object.keys(j.result?.metrics || {}))),
    ).filter((k) =>
      selected.some((j) => typeof j.result?.metrics?.[k] === "number"),
    );
    const compareKeys = [
      "region",
      "provider_uri",
      "market",
      "benchmark",
      "test_start",
      "test_end",
    ];
    const mismatch = compareKeys.some((k) =>
      selected.some((j) => j.config?.[k] !== selected[0].config?.[k]),
    );
    return `<div class="compare-header"><h2>指标比较 <span class="muted" style="font-size:12px">/ ${selected.length} 个实验</span></h2>${button("清除选择", "clear-comparison", "small")}</div>${mismatch ? `<div style="margin-bottom:15px">${notice("所选实验的市场、数据源、基准或测试区间不同，指标不可直接公平比较。", "warning")}</div>` : ""}<div class="card">${keys.length ? `<div class="table-wrap"><table class="comparison-values"><thead><tr><th>指标</th>${selected.map((j) => `<th>${esc(j.name)}<br><span class="mono">${esc(j.id.slice(0, 8))} · ${esc(j.config?.model)}</span></th>`).join("")}</tr></thead><tbody>${keys.map((k) => `<tr><td class="mono">${esc(k)}</td>${selected.map((j) => `<td class="mono">${metricFormat(k, j.result?.metrics?.[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : empty("所选实验尚无共同可显示的数值指标", "请在各自的任务结果中查看输出与日志。", "", "chart")}</div>`;
  }
  function capabilitiesView() {
    return `${heading("Qlib 功能地图", "清楚知道哪些能力已经接入，哪些仍需要专门的 Python 工作流。")}<div class="grid-2">${state.catalog.capabilities.map((c, i) => `<article class="card capability-card"><div class="cap-icon">${icon(["database", "cube", "chart", "terminal", "code", "download", "refresh", "layers", "settings"][i % 9])}</div><div class="cap-content"><h3>${esc(c.name)}${badge(c.status)}</h3><p>${esc(c.description)}</p>${c.url ? `<a href="${safeLink(c.url)}" target="_blank" rel="noopener noreferrer">阅读 Qlib 官方文档 ↗</a>` : ""}</div></article>`).join("")}</div><div style="margin-top:20px">${notice("控制台使用受限的内置预设与参数。它不提供任意 Python 执行、pickle 上传、强化学习一键运行或真实券商交易；需要扩展时请在仓库中审查并添加代码。")}</div>${footer()}`;
  }
  function setValidation(content) {
    const area = $("#validation-result");
    if (area) area.innerHTML = content;
  }
  async function validateConfig() {
    const data = await api("/config/validate", {
      method: "POST",
      body: formConfig(),
    });
    state.validated = data;
    state.lastYaml = data.yaml;
    setValidation(
      notice("配置校验通过。可预览、导出或开始运行。", "success") +
        (data.warnings || []).map((w) => notice(w, "warning")).join(""),
    );
    return data;
  }
  function download(text, filename, type = "text/plain;charset=utf-8") {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function downloadYaml() {
    if (!state.lastYaml) throw new Error("请先校验并生成 YAML。");
    download(
      state.lastYaml,
      `${(state.draft.name || "workflow").replace(/[^\w\u4e00-\u9fff-]/g, "_")}.yaml`,
      "application/yaml;charset=utf-8",
    );
  }
  async function saveConfig() {
    const config = formConfig();
    const saved = await api("/configs", { method: "POST", body: config });
    state.configs = (await api("/configs")).items || [];
    const side = $(".form-side .save-list")?.parentElement;
    if (side) side.innerHTML = savedConfigs();
    else if (state.route === "workflow") {
      const cards = $$(".form-side article");
      if (cards[1]) $(".card-body", cards[1]).innerHTML = savedConfigs();
    }
    const savedHeader = $$(".form-side article")[1];
    if (savedHeader && $(".card-head p", savedHeader))
      $(".card-head p", savedHeader).textContent =
        `${state.configs.length} 份研究设置`;
    toast(`已保存「${saved.name || config.name}」`);
  }
  function syncDataInputs() {
    const provider = $("#data-provider");
    const region = $("#field-data-region");
    if (provider) state.draft.provider_uri = provider.value.trim();
    if (region) state.draft.region = region.value;
  }
  async function checkData() {
    syncDataInputs();
    const provider = state.draft.provider_uri,
      region = state.draft.region;
    if (!provider) throw new Error("请填写本地 Qlib 数据目录。");
    const target = $("#data-status-result");
    if (target)
      target.innerHTML =
        '<div class="loading-inline"><span class="spinner"></span>正在检查本地数据结构…</div>';
    try {
      const data = await api(
        `/data/status?${new URLSearchParams({ provider_uri: provider, region })}`,
      );
      state.dataStatus = data;
      state.dataSource = { provider_uri: provider, region };
      state.dataChecked = true;
      state.dataError = "";
      if ($("#data-status-result"))
        $("#data-status-result").innerHTML = dataStatusContent();
    } catch (err) {
      state.dataError = err.message;
      if ($("#data-status-result"))
        $("#data-status-result").innerHTML = dataStatusContent();
      throw err;
    }
  }
  async function submitJob(kind) {
    if (state.busy.has("submit-job")) return;
    state.busy.add("submit-job");
    try {
      let config;
      if (["inspect", "features"].includes(kind)) {
        syncDataInputs();
        config = formConfig();
      } else config = formConfig();
      const body = { kind, config };
      if (kind === "backtest") {
        body.source_job_id = $("#source-job")?.value;
        if (!body.source_job_id)
          throw new Error(
            "请先选择一个已完成的训练或完整工作流，作为回测预测来源。",
          );
      }
      if (kind === "features") {
        const form = $("#query-form");
        if (!form?.reportValidity())
          throw new Error("请填写证券、字段与查询日期。");
        body.query = {
          instruments: state.query.instruments
            .split(/[,，\n]+/)
            .map((v) => v.trim())
            .filter(Boolean),
          fields: state.query.fields
            .split(/\n+/)
            .map((v) => v.trim())
            .filter(Boolean),
          start_time: state.query.start_time,
          end_time: state.query.end_time,
        };
        if (body.query.start_time > body.query.end_time)
          throw new Error("查询开始日期不可晚于结束日期。");
      }
      const job = await api("/jobs", { method: "POST", body });
      state.jobs = [job, ...state.jobs.filter((j) => j.id !== job.id)];
      state.jobId = job.id;
      state.jobTab = "logs";
      toast(`${kindLabels[kind]}已加入任务队列`);
      navigate("jobs", job.id);
    } finally {
      state.busy.delete("submit-job");
    }
  }
  async function loadJob(id, force = false) {
    const key = ++state.detailKey;
    if (state.job?.id !== id) {
      state.job = null;
      state.logs = "";
      state.logOffset = 0;
      state.artifacts = [];
    }
    const offset = state.logOffset;
    try {
      const [job, logs, artifacts] = await Promise.all([
        api(`/jobs/${encodeURIComponent(id)}`),
        api(`/jobs/${encodeURIComponent(id)}/logs?offset=${offset}`),
        api(`/jobs/${encodeURIComponent(id)}/artifacts`),
      ]);
      if (
        key !== state.detailKey ||
        state.jobId !== id ||
        state.route !== "jobs"
      )
        return;
      const changed = JSON.stringify(state.job) !== JSON.stringify(job);
      state.job = job;
      if (offset === state.logOffset) {
        state.logs += logs.text || "";
        state.logOffset = logs.next_offset ?? offset + (logs.text || "").length;
      }
      const artifactChanged =
        JSON.stringify(state.artifacts) !==
        JSON.stringify(artifacts.items || []);
      state.artifacts = artifacts.items || [];
      const el = $("#job-details");
      if (!el) return;
      if (force || changed || artifactChanged) {
        const old = $("#log-output");
        const bottom = old
          ? old.scrollHeight - old.scrollTop - old.clientHeight < 40
          : true;
        const top = old?.scrollTop || 0;
        el.innerHTML = jobDetailContent();
        const next = $("#log-output");
        if (next) next.scrollTop = bottom ? next.scrollHeight : top;
      } else if (state.jobTab === "logs" && $("#log-output")) {
        const logEl = $("#log-output");
        const bottom =
          logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
        logEl.textContent =
          state.logs ||
          (["queued", "running"].includes(job.status)
            ? "等待进程输出…"
            : "此任务没有日志输出。");
        if (bottom) logEl.scrollTop = logEl.scrollHeight;
      }
    } catch (err) {
      if (
        key === state.detailKey &&
        state.route === "jobs" &&
        $("#job-details")
      )
        $("#job-details").innerHTML =
          `<div class="card-body">${notice(`无法读取任务：${err.message}`, "error")}${button("重试", "retry-job", "small", "", 'style="margin-top:15px"')}</div>`;
    }
  }
  async function refreshWorkspace(manual = false) {
    if (state.polling) return;
    state.polling = true;
    try {
      const [health, jobs, experiments] = await Promise.all([
        api("/health"),
        api("/jobs"),
        api("/experiments"),
      ]);
      const jobsChanged =
        JSON.stringify(state.jobs) !== JSON.stringify(jobs.items || []);
      const experimentsChanged =
        JSON.stringify(state.experiments) !==
        JSON.stringify(experiments.items || []);
      state.health = health;
      state.jobs = jobs.items || [];
      state.experiments = experiments.items || [];
      state.connected = true;
      updateStatus();
      if (manual) {
        state.configs = (await api("/configs")).items || [];
        if (state.route === "workflow")
          toast("运行状态已刷新，正在编辑的配置已保留");
        else renderView();
      } else if (state.route === "jobs") {
        if (jobsChanged && $("#job-list"))
          $("#job-list").innerHTML = jobListContent();
        if ($("#job-total")) $("#job-total").textContent = state.jobs.length;
        if ($("#job-active"))
          $("#job-active").textContent = activeJobs().length;
        if (state.jobId) await loadJob(state.jobId);
      } else if (state.route === "overview" && jobsChanged)
        $("#main").innerHTML = overviewView();
      else if (state.route === "experiments" && experimentsChanged)
        $("#main").innerHTML = experimentsView();
    } catch (err) {
      state.connected = false;
      updateStatus();
      if (manual) throw err;
    } finally {
      state.polling = false;
    }
  }
  function handleFormInput(event) {
    const el = event.target,
      name = el.name;
    if (!name) return;
    if (name.startsWith("query-")) {
      state.query[name.slice(6)] = el.value;
      return;
    }
    if (name === "data-provider") {
      state.draft.provider_uri = el.value;
      state.dataChecked = false;
      return;
    }
    if (name === "data-region") {
      const region = state.catalog.regions[el.value];
      state.draft.region = el.value;
      state.draft.provider_uri = region.provider_uri;
      state.draft.market = region.market;
      state.draft.benchmark = region.benchmark;
      if ($("#data-provider")) $("#data-provider").value = region.provider_uri;
      state.dataChecked = false;
      state.dataError = "";
      if ($("#data-status-result"))
        $("#data-status-result").innerHTML = dataStatusContent();
      return;
    }
    if (!el.closest("#workflow-form")) return;
    if (name.endsWith("_kwargs")) state.jsonDraft[name] = el.value;
    else
      state.draft[name] =
        el.type === "number"
          ? el.value === ""
            ? ""
            : Number(el.value)
          : el.value;
    state.validated = null;
    state.lastYaml = "";
    setValidation("");
    if ($("#workflow-summary"))
      $("#workflow-summary").innerHTML = summaryContent();
  }
  function handleFormChange(event) {
    const el = event.target,
      name = el.name;
    if (el.id === "source-job" && el.value) {
      const source = state.jobs.find((job) => job.id === el.value);
      if (!source?.config) return;
      const sourceFields = [
        "region",
        "provider_uri",
        "market",
        "model",
        "handler",
        "train_start",
        "train_end",
        "valid_start",
        "valid_end",
        "test_start",
        "test_end",
        "model_kwargs",
        "handler_kwargs",
      ];
      for (const key of sourceFields) {
        state.draft[key] = clone(source.config[key]);
        const field = $(`[name="${key}"]`);
        if (key.endsWith("_kwargs")) {
          state.jsonDraft[key] = JSON.stringify(
            source.config[key] || {},
            null,
            2,
          );
          if (field) field.value = state.jsonDraft[key];
        } else if (field) field.value = source.config[key];
      }
      state.draft.time_range = source.config.time_range;
      $('[name="time_range"]').value = state.draft.time_range;
      state.validated = null;
      state.lastYaml = "";
      setValidation("");
      $("#workflow-summary").innerHTML = summaryContent();
      $("#model-guidance").innerHTML = modelGuidance();
      toast("已同步来源实验的研究配置；当前策略、资金与费用已保留");
      return;
    }
    if (el.id === "job-filter") {
      state.jobFilter = el.value;
      $("#job-list").innerHTML = jobListContent();
      return;
    }
    if (el.dataset.experiment) {
      if (el.checked) state.selected.add(el.dataset.experiment);
      else state.selected.delete(el.dataset.experiment);
      $("#comparison").innerHTML = comparisonContent(
        state.experiments.filter((j) => state.selected.has(j.id)),
      );
      return;
    }
    if (!el.closest("#workflow-form")) return;
    if (name === "region") {
      const region = state.catalog.regions[el.value];
      for (const key of [
        "provider_uri",
        "market",
        "benchmark",
        "open_cost",
        "close_cost",
        "min_cost",
      ]) {
        if (region[key] !== undefined) {
          state.draft[key] = region[key];
          const field = $(`[name="${key}"]`);
          if (field) field.value = region[key];
        }
      }
    }
    if (name === "time_range" && el.value !== "custom") {
      const preset = state.catalog.times[el.value];
      for (const key of ["train", "valid", "test"])
        for (const [i, side] of ["start", "end"].entries()) {
          state.draft[`${key}_${side}`] = preset[key][i];
          $(`[name="${key}_${side}"]`).value = preset[key][i];
        }
    }
    if (/^(train|valid|test)_(start|end)$/.test(name)) {
      state.draft.time_range = "custom";
      $('[name="time_range"]').value = "custom";
    }
    if (name === "strategy") {
      const preset = state.catalog.strategies[el.value];
      for (const key of ["topk", "n_drop"]) {
        state.draft[key] = preset.kwargs[key];
        $(`[name="${key}"]`).value = preset.kwargs[key];
      }
      $("#strategy-guidance").innerHTML = strategyGuidance();
    }
    if (name === "model" || name === "handler")
      $("#model-guidance").innerHTML = modelGuidance();
    if ($("#workflow-summary"))
      $("#workflow-summary").innerHTML = summaryContent();
  }
  async function copyLogs() {
    try {
      await navigator.clipboard.writeText(state.logs || "");
      toast("日志已复制");
    } catch (_) {
      throw new Error(
        "浏览器未允许剪贴板写入。可在日志框中选中文本后手动复制。",
      );
    }
  }
  async function runAction(action, el) {
    if (action.startsWith("goto-")) {
      navigate(action.slice(5));
      return;
    }
    switch (action) {
      case "toggle-menu": {
        const open = $(".shell").classList.toggle("menu-open");
        $(".menu-button").setAttribute("aria-expanded", String(open));
        return;
      }
      case "refresh":
        await refreshWorkspace(true);
        return;
      case "retry-start":
        await start();
        return;
      case "new-workflow":
        setDraft(state.catalog.default_config);
        navigate("workflow");
        return;
      case "template": {
        const template = state.catalog.templates.find(
          (t) => t.id === el.dataset.id,
        );
        if (!template) return;
        setDraft({
          ...clone(state.catalog.default_config),
          ...clone(template.config),
          name: template.name,
        });
        navigate("workflow");
        toast(`已加载「${template.name}」模板`);
        return;
      }
      case "select-model": {
        const id = el.dataset.id;
        state.draft.model = id;
        state.draft.model_kwargs = {};
        state.jsonDraft.model_kwargs = "{}";
        if (deepModels.includes(id)) state.draft.handler = "alpha360";
        state.validated = null;
        navigate("workflow");
        return;
      }
      case "load-config": {
        const config = state.configs.find((c) => c.id === el.dataset.id);
        if (config) {
          setDraft(config.config);
          renderView();
          toast(`已加载「${config.name}」`);
        }
        return;
      }
      case "save-config":
        await saveConfig();
        return;
      case "validate":
        await validateConfig();
        toast("配置校验通过");
        return;
      case "preview-yaml": {
        const result = await validateConfig();
        $("#dialog-body").innerHTML =
          `<p class="narrow-note" style="margin-bottom:12px">已根据当前表单生成 Qlib 原生工作流配置，可导出用于 qrun。</p><pre class="config-pre">${esc(result.yaml)}</pre>`;
        $("#preview-dialog").showModal();
        return;
      }
      case "export-yaml":
        await validateConfig();
        downloadYaml();
        return;
      case "download-yaml":
        downloadYaml();
        return;
      case "close-dialog":
        $("#preview-dialog").close();
        return;
      case "data-status":
        await checkData();
        return;
      case "run-pipeline":
      case "run-train":
      case "run-backtest":
      case "run-inspect":
      case "run-features":
        await submitJob(action.slice(4));
        return;
      case "open-job": {
        state.jobId = el.dataset.id;
        state.jobTab = "results";
        navigate("jobs", el.dataset.id);
        return;
      }
      case "retry-job":
        await loadJob(state.jobId, true);
        return;
      case "job-tab": {
        state.jobTab = el.dataset.tab;
        const target = $("#job-details");
        if (target && state.job) {
          target.innerHTML = jobDetailContent();
          if (state.jobTab === "logs" && $("#log-output"))
            $("#log-output").scrollTop = $("#log-output").scrollHeight;
        }
        return;
      }
      case "cancel-job": {
        const job = await api(
          `/jobs/${encodeURIComponent(el.dataset.id)}/cancel`,
          { method: "POST", body: {} },
        );
        state.jobs = state.jobs.map((j) => (j.id === job.id ? job : j));
        toast(job.status === "cancelled" ? "任务已取消" : "取消请求已处理");
        await loadJob(job.id, true);
        if ($("#job-list")) $("#job-list").innerHTML = jobListContent();
        updateStatus();
        return;
      }
      case "copy-logs":
        await copyLogs();
        return;
      case "use-job-config":
        if (state.job?.config) {
          setDraft(state.job.config);
          navigate("workflow");
          toast("已加载此任务的配置");
        }
        return;
      case "clear-comparison":
        state.selected.clear();
        renderView();
        return;
    }
  }
  document.addEventListener("click", async (event) => {
    const el = event.target.closest("[data-action]");
    if (!el || el.disabled) return;
    event.preventDefault();
    const action = el.dataset.action;
    if (state.busy.has(action)) return;
    state.busy.add(action);
    const wasDisabled = el.disabled;
    el.disabled = true;
    try {
      await runAction(action, el);
    } catch (err) {
      toast(err.message || "操作失败，请重试。", "error");
      if (
        [
          "validate",
          "preview-yaml",
          "export-yaml",
          "run-pipeline",
          "run-train",
          "run-backtest",
          "save-config",
        ].includes(action)
      )
        setValidation(notice(err.message, "error"));
    } finally {
      state.busy.delete(action);
      if (el.isConnected) el.disabled = wasDisabled;
    }
  });
  document.addEventListener("input", handleFormInput);
  document.addEventListener("change", handleFormChange);
  document.addEventListener("submit", (event) => {
    event.preventDefault();
  });
  document.addEventListener("keydown", (event) => {
    if (
      event.key === "Escape" &&
      $(".shell")?.classList.contains("menu-open")
    ) {
      $(".shell").classList.remove("menu-open");
      $(".menu-button").setAttribute("aria-expanded", "false");
      $(".menu-button").focus();
    }
    if (
      event.target.matches?.('[role="tab"]') &&
      ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
    ) {
      event.preventDefault();
      const tabs = $$('[role="tab"]');
      const current = tabs.indexOf(event.target);
      const next =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? tabs.length - 1
            : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) %
              tabs.length;
      const tab = tabs[next];
      const name = tab.dataset.tab;
      state.jobTab = name;
      $("#job-details").innerHTML = jobDetailContent();
      $(`#tab-${name}`).focus();
    }
  });
  window.addEventListener("hashchange", () => {
    renderView();
    window.scrollTo(0, 0);
  });
  $("#preview-dialog").addEventListener("click", (event) => {
    if (event.target === $("#preview-dialog")) {
      const box = event.target.getBoundingClientRect();
      if (
        event.clientX < box.left ||
        event.clientX > box.right ||
        event.clientY < box.top ||
        event.clientY > box.bottom
      )
        event.target.close();
    }
  });
  async function start() {
    try {
      const [session, catalog, health, jobs, configs, experiments] =
        await Promise.all([
          api("/session"),
          api("/catalog"),
          api("/health"),
          api("/jobs"),
          api("/configs"),
          api("/experiments"),
        ]);
      state.csrf = session.csrf_token;
      state.catalog = catalog;
      state.health = health;
      state.jobs = jobs.items || [];
      state.configs = configs.items || [];
      state.experiments = experiments.items || [];
      if (!state.draft) setDraft(catalog.default_config);
      state.connected = true;
      shell();
    } catch (err) {
      $("#app").innerHTML =
        `<main class="boot-state"><div class="empty-icon">${icon("terminal")}</div><h1>暂时无法连接工作台</h1><p class="muted" style="max-width:600px;text-align:center;padding:0 25px">${esc(err.message)}</p>${button("重新连接", "retry-start", "primary", "refresh")}<p class="narrow-note">请确认本地 Qlib Console 服务正在运行。</p></main>`;
    }
  }
  start();
  setInterval(() => {
    if (state.catalog && !document.hidden) refreshWorkspace();
  }, 3000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && state.catalog) refreshWorkspace();
  });
})();
