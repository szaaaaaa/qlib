# 本分支验证记录

日期：2026-10-05。原始基线：`0562e6ce65d4bb1271874f9092f4d075b2c3e98a`。

## 已通过

- `QLIB_CONSOLE_INTEGRATION=1 python -m pytest tests/web -q`：**64 passed**，另有 31 个参数化 subtests；1 条上游 Starlette/httpx 弃用提示。
- 真实执行器的完整集成测试在修复异步日志竞争后连续运行三次：每次 **30 passed**，不是仅运行 mocks。
- `python -m black --check --line-length 120 qlib_trader/web tests/web`。
- `node --check qlib_trader/web/static/app.js` 和 `node --check tests/web/frontend_dom.cjs`。
- `python -m compileall -q qlib_trader/web` 和 `git diff --check`。
- 源代码 wheel 构建、产物内容检查，以及独立安装后的 `/`、JS/CSS 静态文件和 `/api/catalog` HTTP smoke。
- 独立代码复核：表达式执行边界、文件路径与类型限制、无上传 pickle、源实验不可改写、线程/进程生命周期、取消与异常退出恢复。

### 真实 Qlib 覆盖

测试临时生成固定随机种子的日频二进制数据：8 只合成证券和一个合成基准，共 340 个交易日。它依次执行数据深度检查、因子表达式查询、Linear 训练、Linear 完整流水线、复用训练预测的新实验回测，以及 LightGBM 完整流水线。训练产生 400 条预测，每个回测产生 50 天报告；复用源预测的结果与独立 Linear 流水线一致，源实验保持不变。

这验证的是软件链路和报告口径，不是真实市场数据质量、投资策略有效性或未来收益。

### 前端覆盖

8 项前端测试包括纯 Node 渲染/转义/图表测试，以及 JSDOM 连接真实 FastAPI 的交互测试。覆盖 24 个配置字段、市场/日期预设、重复校验/保存/加载、错误 JSON/日期恢复、YAML 弹窗/导出、恶意名称转义、模型目录、数据检查/因子查询、实际排队和取消、源配置复制、任务过滤、菜单关闭、CSRF 和无 JavaScript 错误。

## 未通过或未执行

- 全仓库 Black：**未通过**。使用相同 Black 26.10.0 对原始基线单独检查，也有相同的 **58 个既有文件**需要格式化；本分支未扩大这个问题，也未重排无关源代码。
- 原生浏览器鼠标、视觉布局、移动端视口及截图：**未验证**。本次环境中独立 Chromium 因 AF_UNIX socket 权限无法启动，受支持的云浏览器访问本地服务返回 `ERR_BLOCKED_BY_CLIENT`。未绕过限制，未制作假截图。JSDOM 不替代这些测试。
- 真实行情长期回测、XGBoost/CatBoost/四种深度学习模型训练、多平台运行、完整上游 Qlib 测试矩阵：**未执行**。
- Windows worker 后代进程回收：**未实测**；实现了父进程监控和主 worker 终止，但复杂后代进程树回收仍需验证。

## 实测环境

Linux、Python 3.12.14、Node 24.19.0；Qlib 使用当前仓库源代码并以 GCC/G++ 编译 Cython 扩展。

主要包版本：FastAPI 0.141.1、Pydantic 2.13.4、MLflow 3.16.1、LightGBM 4.7.0、NumPy 2.3.5、Pandas 2.2.3、pytest 9.1.1、Black 26.10.0。Node 可选测试依赖由 `tests/web/package-lock.json` 固定。

完整复现命令与功能边界见 [控制台 README](README.md)。专用 GitHub Actions 工作流测试 Python 3.10/3.12 的轻量 API、任务、前端 DOM 与格式，不下载市场数据；真实 Qlib 合成行情集成测试通过环境变量显式开启。
