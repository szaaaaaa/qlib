# Qlib 可视化研究控制台

中文、单用户、本地 Web 控制台。页面直接调用 FastAPI，训练、信号分析和回测在独立 Python 进程中执行 Qlib；没有模拟收益、自动实盘交易或远程演示后台。

## 启动

建议使用 Python 3.10–3.12 的独立虚拟环境，在仓库根目录运行：

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[web]'
python -m qlib_trader.web
```

浏览器打开 http://127.0.0.1:8765 。安装后也可运行 `qlib-console`。CLI 原入口 `python -m qlib_trader` 保持可用。

从源代码安装 Qlib 需要 C/C++ 编译器以及 Python 开发头文件。Linux 可使用 GCC/G++，macOS 可使用 Xcode Command Line Tools，Windows 请使用匹配 Python 的 Microsoft C++ Build Tools。若本机环境错误地指定了不存在的 clang，可在已安装 GCC 的 Linux 上使用 `CC=gcc CXX=g++ python -m pip install -e '.[web]'`。

如果只想先打开 UI、编辑配置，不安装模型运行环境：

```bash
python -m pip install -r qlib_trader/web/requirements.txt
python -m qlib_trader.web
```

此时界面会列出缺失的运行依赖。实际训练仍需安装 Qlib 及对应模型包。树模型 LightGBM 随 Qlib 安装；XGBoost、CatBoost、PyTorch 按所选模型单独安装。

```bash
python -m qlib_trader.web --port 8766 --storage-dir /path/to/private-console-data
```

只允许回环地址，不提供 `0.0.0.0` 选项。每个存储目录只启动一个服务进程。不要用多 worker、反向代理或端口转发把它开放到公网。

## 首次使用

1. 准备已有的 Qlib 日频二进制行情目录，包含 `calendars/day.txt`、`instruments/all.txt`、对应市场的证券列表和 `features/`。
2. 在“数据中心”中填写目录并检查状态；“深度检查”实际调用 Qlib，验证日历和股票池。
3. 在“工作流”选择模板、市场/股票池、模型、因子集、训练/验证/测试区间、费用和策略参数。区间不得重叠。
4. 先“校验配置”，查看提示和原生 Qlib YAML，再提交训练或完整流水线。
5. 在任务中心查看真实日志、状态和结果，下载 CSV/JSON/YAML。训练完成后可选择该实验的预测单独重新回测。

数据不会自动下载、覆盖或上传。仓库 README 说明原官方数据集下载暂不可用，请使用自己有权使用的数据源；示例日期是历史模板，必须调整到实际数据覆盖范围。回测需要测试结束日之后至少一个交易日，前瞻收益标签通常还需要更多未来行情。

## 功能覆盖

| 范围 | 当前状态 | 具体内容 |
| --- | --- | --- |
| 总览 | 已实现 | 环境/依赖、数据状态、真实任务摘要、快速入口 |
| 配置与模板 | 已实现 | 5 个模板、保存/加载、原生 qrun YAML 导出、参数校验 |
| 数据与因子 | 已实现 | 本地结构检查、实际日历/证券池检查、限定数值表达式查询、CSV 导出 |
| 模型 | 已接入 | LightGBM、XGBoost、CatBoost、Linear、LSTM、GRU、ALSTM、Transformer |
| 因子集 | 已接入 | Alpha158、Alpha360；标签可用受限表达式配置 |
| 训练和信号 | 已实现 | 真正的模型训练、预测、IC/Rank IC 分析、预测与标签下载 |
| 回测 | 已实现 | 完整流水线、基于已完成训练的单独回测、TopK/淘汰数/资金/费用/基准配置 |
| 任务管理 | 已实现 | 顺序队列、独立进程、持久化日志、取消、失败/中断、最多 32 个活动任务 |
| 分析与比较 | 已实现 | 收益/基准/超额/回撤曲线、指标、控制台实验比较、安全产物下载 |
| 数据采集/更新 | 外部工作流 | 使用仓库 `scripts/data_collector`；界面提供范围说明，不隐式下载 |
| 在线/滚动训练 | 外部工作流 | 保留仓库 `examples/online_srv`、`examples/rolling` Python 工作流 |
| RL、高频执行、风险模型 | 外部工作流 | 功能导航与文档入口；尚无完整可执行表单，需要专用数据/环境 |
| 任意 Python 扩展 | 代码层扩展 | 需添加经审查的预设；网页不接受任意模块、命令或上传的 pickle |
| 券商和实盘交易 | 不提供 | 仅研究和历史回测 |

“所有功能”并不意味着把 Qlib 的全部任意 Python API 都开放为网页执行。此分支覆盖仓库 `qlib_trader` 的主要研究闭环，并明确标出高级框架的边界。

### 模型与策略细节

- Transformer 绑定真正的 Qlib `TransformerModel`，不会误调用其底层 torch 网络类。
- 深度学习默认 CPU（`GPU=-1`），Alpha360 使用 `d_feat=6`。Alpha158 在这些模型中表示单步特征，不等于 60 步时序输入。
- 原 CLI 的 `topk_weighted` 实际也是 `TopkDropoutStrategy`；本界面将其标为“集中持仓 TopK”，不宣传为独立加权算法。
- 高级 JSON 参数经过白名单检查。不能传入任意类、路径、回调、处理器对象或 Python 源码。
- XGBoost/CatBoost 原生包装器固定使用 `fit()` 默认的 1000 轮、50 轮早停；忽略的 `n_estimators` / `iterations` / `num_boost_round` 构造参数不在网页接受范围内。ALSTM 原生包装器忽略的 `rnn_type` 同样不对外暴露。
- 一个模型在目录中“依赖可用”只代表所需包可被找到，不保证硬件、数据或所有参数组合都适用。

### 报告约定

曲线使用 Qlib 的日收益算术累加口径：策略收益减交易成本，再逐日累计；超额收益再减基准收益。不是复利净值。回撤是成本后累计收益相对含初始零点的历史峰值的差。风险指标来自 Qlib 本身，名称保留原始维度。非有限值不会伪造为零，缺失/无效报告会导致任务失败并显示原因。

实验列表仅包含当前控制台存储目录创建的实验，不自动导入其他 `mlruns` 或远程 MLflow 服务。单独回测复制源预测和标签到新 recorder，不覆盖原训练实验。

## 开发

本次运行证据和未验证范围见 [验证记录](TESTING.md)。

模块职责：

- `schema.py`：Pydantic 配置、预设目录、表达式 AST 白名单、原生工作流编译
- `api.py`：同源 JSON API、文件下载和静态文件
- `jobs.py`：磁盘状态、单工作进程队列、取消/超时/重启恢复
- `runner.py`：真实 Qlib 数据/训练/预测/回测、可信本地产物读取和 CSV 导出
- `static/`：无构建步骤、无 CDN 的原生 HTML/CSS/JavaScript 前端
- `tests/web/`：配置、HTTP API、安全边界、任务状态、执行器和可选真实集成测试

### 测试

```bash
python -m pip install -r qlib_trader/web/requirements-dev.txt numpy pandas
python -m pytest tests/web -q
python -m black --check --line-length 120 qlib_trader/web tests/web
node --check qlib_trader/web/static/app.js
```

可选的真实 API + JSDOM 交互测试（Node 22.12+，建议 Node 24）：

```bash
npm --prefix tests/web ci --ignore-scripts
python -m pytest tests/web/test_frontend.py -q
```

该测试自动启动独立临时目录和随机回环端口，验证表单、重复操作、弹窗、导出、错误恢复、排队/取消与 CSRF；不会连接用户正在使用的服务。JSDOM 不验证 CSS 视觉布局、真实浏览器焦点行为或移动视口。

真实 Qlib 合成行情集成测试（需要已经安装/编译当前仓库 Qlib）：

```bash
# macOS / Linux
QLIB_CONSOLE_INTEGRATION=1 python -m pytest tests/web/test_runner.py -q
# PowerShell
$env:QLIB_CONSOLE_INTEGRATION="1"
python -m pytest tests/web/test_runner.py -q
```

测试只在临时目录生成合成行情，不下载真实市场数据，不代表模型有任何投资价值。完整上游 Qlib 测试矩阵、所有深度模型训练、真实市场长期回测和多平台浏览器测试不包含在此轻量测试内。

### API 摘要

- `GET /api/session`：当前会话令牌；所有 POST 必须携带 `X-Console-Token`
- `GET /api/health`、`/api/catalog`：依赖检查、可运行预设及能力范围
- `GET /api/data/status`：只读结构检查
- `POST /api/config/validate`：配置规范化、校验与原生 YAML
- `GET/POST /api/configs`：本地配置列表/保存
- `GET/POST /api/jobs`：任务列表/创建；类型为 pipeline、train、backtest、inspect、features
- `GET /api/jobs/{id}`、`/logs?offset=0`、`/artifacts`：状态/增量日志/产物
- `POST /api/jobs/{id}/cancel`：幂等取消
- `GET /api/experiments`：当前控制台的已完成实验
- `GET /openapi.json`：机器可读的 API 结构（离线界面不依赖外部 Swagger CDN）

### 安全与运行边界

服务是本机单用户工具，不是多租户平台。Host 检查、防跨站令牌、同源策略、无 CORS、CSP 和禁止 iframe 用于减少恶意网页访问本地服务的风险。它们不能替代主机账户安全或网络身份认证。

服务和任务使用同一个本机账户权限；只应由可信本机用户运行。MLflow 固定为本控制台的私有本地目录，任务不继承远端跟踪地址。不能读取外部 recorder、上传 pickle 或通过 API 指定执行命令。已有目录中被恶意替换的可信模型/实验文件仍可能不安全，不要使用他人提供的控制台存储目录。

数据源仅支持本机目录，不支持 URL/NFS 自动挂载。任务串行运行，以避免 Qlib 全局初始化互相污染；每项任务限时 6 小时、日志限 32 MiB。启动时遗留 queued/running 状态标记 interrupted，避免重复执行。Worker 持有独立锁，并监控父进程存活；POSIX 下父进程异常退出会终止 worker 进程组。停止服务会中断未完成任务，重新运行会创建新的任务 ID。Windows 的取消会终止主 worker，复杂模型的第三方后代进程回收需在该平台额外验证。

配置、日志、实验和模型保存在 `~/.qlib/console/`（或指定目录），持续积累；本版本不提供删除接口。请按本机文件权限和正常备份/清理流程管理存储。
