"""Dependency-free frontend rendering checks. Real browser QA is a separate step.

Node is optional for Python-only installations. These tests execute the actual
frontend functions in a minimal DOM shell, not a browser or a screenshot engine.
"""

import json
import os
import socket
import tempfile
import threading
import time
import shutil
import subprocess
import unittest
from pathlib import Path

from qlib_trader.web.schema import SOURCE_FIELDS, catalog

STATIC = Path(__file__).resolve().parents[2] / "qlib_trader" / "web" / "static"
NODE = shutil.which("node")

HARNESS = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {};
const element = () => ({innerHTML:'', value:'', textContent:'', addEventListener(){}, reportValidity(){return true;}});
const document = {
  querySelector(selector){return nodes[selector] ||= element();},
  querySelectorAll(){return [];}, addEventListener(){},
};
const context = vm.createContext({document, window:{addEventListener(){}}, location:{origin:'http://127.0.0.1:8765'}, URL,
  setTimeout(){}, clearTimeout(){}, console, JSON, navigator:{},
});
let source = fs.readFileSync(input.source, 'utf8');
const marker = '\n  start();\n';
assert(source.includes(marker), 'Application bootstrap marker must be present');
source = source.replace(marker, `
  globalThis.test = {state, setDraft, formConfig, overviewView, workflowView, modelsView, dataView, jobsView,
    experimentsView, capabilitiesView, resultsContent, seriesChart, previewTable, comparisonContent,
    safeLink, handleFormChange};
  return;
`);
vm.runInContext(source, context);
const t = context.test;
t.state.catalog = input.catalog;
t.state.health = {version:'test',qlib_available:false,dependencies:{},qlib_error:'missing test dependency'};
t.setDraft(input.catalog.default_config);
if(input.case === 'views') {
  for(const name of ['overviewView','workflowView','modelsView','dataView','jobsView','experimentsView','capabilitiesView']) {
    const html=t[name](); assert(html.includes('<h1>'),name); assert(!html.includes('undefined'),name); assert(!html.includes('NaN'),name);
  }
  const workflow=t.workflowView();
  for(const field of Object.keys(input.catalog.default_config)) assert(workflow.includes(`name="${field}"`),field);
  assert.equal((t.modelsView().match(/class="card model-card/g)||[]).length,8);
  assert(t.capabilitiesView().includes('Python 工作流'));
} else if(input.case === 'escaping') {
  const bad='<img src=x onerror=alert(1)>';
  t.state.configs=[{id:'safe-id',name:bad,config:{},updated_at:'2020-01-01'}];
  t.state.jobs=[{id:'b'.repeat(32),name:bad,config:{model:bad,market:bad},status:'failed',kind:'train'}];
  for(const html of [t.overviewView(),t.workflowView(),t.jobsView(),t.previewTable({columns:[bad],rows:[{[bad]:bad}]})]) {
    assert(!html.includes(bad));assert(html.includes('&lt;img'));
  }
  assert.equal(t.safeLink('javascript:alert(1)'),'#');
  assert.equal(t.safeLink('http://evil.invalid/data'),'#');
  assert(t.safeLink('/api/jobs/abc/artifacts/report.csv').startsWith('http://127.0.0.1:8765/api/'));
} else if(input.case === 'charts') {
  assert(t.resultsContent({status:'queued',kind:'pipeline',result:null}).includes('真实结果正在生成'));
  assert(!t.resultsContent({status:'queued',kind:'pipeline',result:null}).includes('<svg viewBox="0 0 720'));
  const rows=Array.from({length:160001},(_,i)=>({date:'2020-01-01',return:i%17/1000,benchmark:null}));
  const html=t.seriesChart(rows,[['return','策略收益','#d8f36a']]);
  assert(html.includes('160001 个时间点'));assert(!html.includes('NaN'));assert(!html.includes('Infinity'));
  assert(html.includes('非复利净值'));
  assert(t.seriesChart([{date:'2020-01-01',return:0}],[['return','收益','#d8f36a']]).includes('<path'));
} else if(input.case === 'comparison') {
  const jobs=[1,2].map(i=>({id:String(i),name:'Experiment '+i,config:{...input.catalog.default_config},result:{metrics:{IC:i/100}}}));
  assert(t.comparisonContent(jobs).includes('0.02'));
  assert(!t.comparisonContent(jobs).includes('不可直接公平比较'));
  jobs[1].config.test_end='2021-01-01';
  assert(t.comparisonContent(jobs).includes('不可直接公平比较'));
  assert(t.comparisonContent([jobs[0]]).includes('再选择至少 1 个'));
} else if(input.case === 'source') {
  const config={...input.catalog.default_config,model:'linear',handler:'alpha360',provider_uri:'/tmp/source',market:'csi500',model_kwargs:{alpha:0.2},handler_kwargs:{drop_raw:true}};
  t.state.jobs=[{id:'source',config}];
  t.state.draft.topk=7;t.state.draft.open_cost=0.01;t.state.draft.account=12345;
  // Source selection's toast is an ordinary DOM append; provide a tiny element.
  document.createElement=()=>({className:'',textContent:'',remove(){}});
  nodes['#toasts']={append(){}};
  t.handleFormChange({target:{id:'source-job',value:'source'}});
  for(const field of input.source_fields) assert.deepEqual(JSON.parse(JSON.stringify(t.state.draft[field])),config[field],field);
  assert.equal(t.state.draft.topk,7);assert.equal(t.state.draft.open_cost,0.01);assert.equal(t.state.draft.account,12345);
  assert.equal(t.formConfig().model_kwargs.alpha,0.2);
} else if(input.case === 'invalid-json') {
  t.state.jsonDraft.model_kwargs='{bad';
  assert.throws(()=>t.formConfig(),/不是有效 JSON/);
  t.state.jsonDraft.model_kwargs='[]';
  assert.throws(()=>t.formConfig(),/JSON 对象/);
  t.state.jsonDraft.model_kwargs='{"alpha": 0.05}';
  assert.equal(t.formConfig().model_kwargs.alpha,0.05);
}
process.stdout.write('ok');
"""


@unittest.skipUnless(NODE, "Node is optional; install it to run frontend unit tests")
class FrontendTests(unittest.TestCase):
    def run_frontend(self, case):
        result = subprocess.run(
            [NODE, "-e", HARNESS],
            input=json.dumps(
                {
                    "source": str(STATIC / "app.js"),
                    "catalog": catalog(),
                    "case": case,
                    "source_fields": list(SOURCE_FIELDS),
                },
                ensure_ascii=False,
            ),
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ok")

    def test_javascript_syntax(self):
        result = subprocess.run([NODE, "--check", str(STATIC / "app.js")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_views_render_and_all_config_fields_are_editable(self):
        self.run_frontend("views")

    def test_external_strings_are_escaped_and_links_are_safe(self):
        self.run_frontend("escaping")

    def test_real_series_zero_and_large_chart_inputs(self):
        self.run_frontend("charts")

    def test_experiment_comparison_marks_incomparable_periods(self):
        self.run_frontend("comparison")

    def test_backtest_source_preserves_strategy_and_costs(self):
        self.run_frontend("source")

    def test_advanced_json_errors_are_recoverable(self):
        self.run_frontend("invalid-json")


@unittest.skipUnless(
    NODE and (Path(__file__).parent / "node_modules" / "jsdom").is_dir(),
    "Optional DOM integration test: npm --prefix tests/web ci",
)
class FrontendDOMIntegrationTests(unittest.TestCase):
    """Run JSDOM against a real API with isolated storage and paused workers.

    This verifies handlers and HTTP behavior; it does not verify browser layout,
    native focus/keyboard handling, CSS, or screenshots.
    """

    def test_real_api_dom_behaviors(self):
        import uvicorn
        from qlib_trader.web.api import create_app

        with tempfile.TemporaryDirectory(prefix="qlib-frontend-dom-") as storage:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(create_app(storage, start_jobs=False), log_level="error"))
            thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
            thread.start()
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            try:
                self.assertTrue(server.started, "Isolated local API failed to start")
                result = subprocess.run(
                    [NODE, str(Path(__file__).with_name("frontend_dom.cjs"))],
                    env={**os.environ, "QLIB_QA_URL": f"http://127.0.0.1:{port}"},
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("zero JS errors", result.stdout)
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                listener.close()


if __name__ == "__main__":
    unittest.main()
