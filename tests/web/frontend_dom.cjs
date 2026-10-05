const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const assert = require("assert/strict");
const path = require("node:path");
const root = path.resolve(__dirname, "../../qlib_trader/web/static");
const base = process.env.QLIB_QA_URL;
if (!base)
  throw new Error(
    "Set QLIB_QA_URL to an isolated test server, or run the pytest integration wrapper.",
  );
const errors = [];
const requests = [];
const downloads = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", (e) => {
  if (!/Not implemented: navigation/.test(e.message)) errors.push(e.message);
});
const dom = new JSDOM(fs.readFileSync(root + "/index.html", "utf8"), {
  url: base,
  runScripts: "outside-only",
  pretendToBeVisual: true,
  virtualConsole,
});
const w = dom.window,
  d = w.document;
w.fetch = (url, options) => {
  requests.push({ url, options });
  return fetch(new URL(url, base), options);
};
w.scrollTo = () => {};
w.URL.createObjectURL = (blob) => {
  downloads.push(blob);
  return "blob:qa";
};
w.URL.revokeObjectURL = () => {};
w.HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
};
w.HTMLDialogElement.prototype.close = function () {
  this.removeAttribute("open");
};
w.navigator.clipboard = {
  writeText: async (text) => {
    w.__clipboard = text;
  },
};
d.addEventListener("click", (event) => {
  if (event.target.closest("a[download]")) event.preventDefault();
});
w.eval(fs.readFileSync(root + "/app.js", "utf8"));
const wait = async (fn) => {
  const stop = Date.now() + 8000;
  while (Date.now() < stop) {
    if (fn()) return;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw Error("Condition timed out. Page: " + d.body.textContent.slice(-1800));
};
const action = async (name, scope = d) => {
  const el = scope.querySelector(`[data-action="${name}"]`);
  assert(el, "missing action " + name);
  assert(!el.disabled, "disabled " + name);
  el.click();
  await new Promise((r) => setTimeout(r, 45));
};
const input = (name, value) => {
  const el = d.querySelector(`[name="${name}"]`);
  assert(el, "missing field " + name);
  el.value = value;
  el.dispatchEvent(new w.Event("input", { bubbles: true }));
  el.dispatchEvent(new w.Event("change", { bubbles: true }));
};
const route = async (hash) => {
  w.location.hash = "#" + hash;
  await wait(() =>
    d.title.startsWith(
      {
        overview: "研究概览",
        workflow: "工作流配置",
        models: "模型目录",
        data: "数据与因子",
        jobs: "任务与结果",
        experiments: "实验对比",
        capabilities: "功能地图",
      }[hash.split("/")[0]],
    ),
  );
};
(async () => {
  await wait(() => d.querySelector(".shell"));
  assert(d.querySelector("h1").textContent.includes("可复现"));
  assert.equal(d.querySelectorAll(".stat-card").length, 4);
  console.log("PASS overview real empty state");
  await action("new-workflow");
  await wait(() => d.querySelector("#workflow-form"));
  assert.equal(
    d.querySelectorAll(
      "#workflow-form input, #workflow-form select, #workflow-form textarea",
    ).length,
    24,
  );
  input("name", "DOM QA <img src=x onerror=alert(1)>");
  input("region", "us");
  assert.equal(d.querySelector("[name=benchmark]").value, "^gspc");
  input("region", "cn");
  assert.equal(d.querySelector("[name=market]").value, "csi300");
  input("model", "linear");
  input("time_range", "short");
  assert.notEqual(d.querySelector("[name=train_start]").value, "2008-01-01");
  await action("validate");
  await wait(() =>
    d.querySelector("#validation-result").textContent.includes("校验通过"),
  );
  await action("validate");
  await wait(() => !d.querySelector("[data-action=validate]").disabled);
  assert.equal(
    requests.filter((r) => r.url === "/api/config/validate").length,
    2,
  );
  input("train_end", "2099-01-01");
  await action("validate");
  await wait(() => d.querySelector("#validation-result .error"));
  input("time_range", "short");
  input("model_kwargs", "{bad");
  await action("preview-yaml");
  assert(!d.querySelector("dialog").hasAttribute("open"));
  input("model_kwargs", "{}");
  await action("preview-yaml");
  await wait(() => d.querySelector("dialog").hasAttribute("open"));
  assert(d.querySelector("#dialog-body").textContent.includes("LinearModel"));
  await action("close-dialog");
  assert(!d.querySelector("dialog").hasAttribute("open"));
  await action("preview-yaml");
  await wait(() => d.querySelector("dialog").hasAttribute("open"));
  await action("download-yaml");
  assert.equal(downloads.length, 1);
  await action("close-dialog");
  await action("export-yaml");
  await wait(() => downloads.length === 2);
  console.log(
    "PASS full workflow, market/time presets, repeated validation, date errors, JSON recovery, repeated dialog and YAML downloads",
  );
  await action("save-config");
  await wait(() => d.querySelectorAll(".save-item").length === 1);
  await action("save-config");
  await wait(() => d.querySelectorAll(".save-item").length === 2);
  assert(!d.querySelector(".save-list img"));
  assert(
    d.querySelectorAll(".form-side .card-head p")[1].textContent.includes("2"),
  );
  input("name", "changed draft");
  await action("load-config");
  await wait(() => d.querySelector("[name=name]").value.startsWith("DOM QA"));
  console.log("PASS repeated saves, load, count refresh, stored-name escaping");
  await route("models");
  assert.equal(d.querySelectorAll(".model-card").length, 8);
  d.querySelector('[data-action="select-model"][data-id="lstm"]').click();
  await wait(() => d.querySelector("#workflow-form"));
  assert.equal(d.querySelector("[name=model]").value, "lstm");
  assert.equal(d.querySelector("[name=handler]").value, "alpha360");
  console.log("PASS model catalogue and compatible deep-learning preset");
  await route("data");
  input("data-region", "us");
  assert(d.querySelector("#data-provider").value.includes("us_data"));
  input("data-region", "cn");
  input("data-provider", "/tmp/qlib-qa-does-not-exist");
  await action("data-status");
  await wait(() =>
    d.querySelector("#data-status-result").textContent.includes("目录不存在"),
  );
  input("query-start_time", "2021-01-01");
  input("query-end_time", "2020-01-01");
  await action("run-features");
  assert(
    d
      .querySelector("#toasts")
      .textContent.includes("查询开始日期不可晚于结束日期"),
  );
  input("query-start_time", "2019-01-01");
  input("query-end_time", "2019-01-31");
  await action("run-features");
  await wait(() => d.querySelector("#log-output"));
  assert(d.querySelector("#job-details").textContent.includes("因子查询"));
  await action("cancel-job");
  await wait(() =>
    d.querySelector("#job-details").textContent.includes("已取消"),
  );
  await action("job-tab");
  console.log(
    "PASS data region/path status, query validation, real queued query, cancel",
  );
  await route("workflow");
  input("model", "linear");
  input("provider_uri", "/tmp/qlib-qa-does-not-exist");
  await action("run-backtest");
  assert(d.querySelector("#toasts").textContent.includes("请先选择一个已完成"));
  await action("run-train");
  await wait(() => d.querySelector("#log-output"));
  await action("cancel-job");
  await wait(() =>
    d.querySelector("#job-details").textContent.includes("已取消"),
  );
  d.querySelector("[data-tab=config]").click();
  await wait(() => d.querySelector("[data-action=use-job-config]"));
  await action("use-job-config");
  await wait(() => d.querySelector("#workflow-form"));
  assert.equal(d.querySelector("[name=model]").value, "linear");
  console.log(
    "PASS real train queue, required backtest source, cancellation, config reuse",
  );
  await route("jobs");
  const filter = d.querySelector("#job-filter");
  filter.value = "completed";
  filter.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert(d.querySelector("#job-list").textContent.includes("暂无匹配任务"));
  await route("experiments");
  assert(d.querySelector("#main").textContent.includes("还没有可以比较"));
  await route("capabilities");
  assert.equal(d.querySelectorAll(".capability-card").length, 9);
  assert(d.querySelector("#main").textContent.includes("Python 工作流"));
  await route("overview");
  await action("toggle-menu");
  assert(d.querySelector(".shell").classList.contains("menu-open"));
  d.dispatchEvent(
    new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
  );
  assert(!d.querySelector(".shell").classList.contains("menu-open"));
  console.log(
    "PASS filters, experiments empty state, capability scope, mobile navigation open/escape",
  );
  assert.equal(errors.length, 0, JSON.stringify(errors));
  assert(
    requests
      .filter((r) => r.options?.method === "POST")
      .every((r) => r.options.headers["X-Console-Token"]),
  );
  console.log("PASS zero JS errors and all POSTs carry CSRF token");
  if (process.env.QLIB_FRONTEND_QA_REPORT)
    fs.writeFileSync(
      process.env.QLIB_FRONTEND_QA_REPORT,
      JSON.stringify(
        {
          suite: "JSDOM + real local FastAPI",
          browserVisualVerification: false,
          assertions: "all passed",
          requests: requests.length,
          errors,
          checkedAt: new Date().toISOString(),
        },
        null,
        2,
      ),
    );
  dom.window.close();
})().catch((e) => {
  console.error(e.stack);
  dom.window.close();
  process.exitCode = 1;
});
