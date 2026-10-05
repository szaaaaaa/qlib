"""Validated, declarative console configuration and Qlib workflow compilation.

No Python, module paths, pickle inputs or arbitrary constructor objects are accepted
from the browser. Adding a model requires a reviewed, code-side preset.
"""

import ast
import copy
import importlib.util
import math
import operator
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from qlib_trader.config import DATASET_HANDLERS, MODEL_PRESETS, REGIONS, STRATEGY_PRESETS, TIME_PRESETS, ConfigBuilder

DEPENDENCIES = {
    "lightgbm": "lightgbm",
    "xgboost": "xgboost",
    "catboost": "catboost",
    "linear": "sklearn",
    "lstm": "torch",
    "gru": "torch",
    "transformer": "torch",
    "alstm": "torch",
}
MODEL_KEYS = {
    "loss",
    "colsample_bytree",
    "learning_rate",
    "subsample",
    "lambda_l1",
    "lambda_l2",
    "max_depth",
    "num_leaves",
    "num_threads",
    "n_estimators",
    "loss_function",
    "depth",
    "iterations",
    "d_feat",
    "hidden_size",
    "num_layers",
    "dropout",
    "n_epochs",
    "lr",
    "early_stop",
    "batch_size",
    "metric",
    "GPU",
    "d_model",
    "nhead",
    "rnn_type",
    "seed",
    "random_state",
    "reg",
    "n_jobs",
    "optimizer",
    "alpha",
    "fit_intercept",
    "estimator",
    "num_boost_round",
    "early_stopping_rounds",
    "min_data_in_leaf",
    "feature_fraction",
    "bagging_fraction",
    "bagging_freq",
    "verbosity",
}
MODEL_ALLOWED = {
    "lightgbm": {
        "loss",
        "colsample_bytree",
        "learning_rate",
        "subsample",
        "lambda_l1",
        "lambda_l2",
        "max_depth",
        "num_leaves",
        "num_threads",
        "num_boost_round",
        "early_stopping_rounds",
        "min_data_in_leaf",
        "feature_fraction",
        "bagging_fraction",
        "bagging_freq",
        "verbosity",
        "seed",
    },
    "xgboost": {"max_depth", "learning_rate", "colsample_bytree", "subsample", "seed", "nthread", "verbosity"},
    "catboost": {"loss", "loss_function", "learning_rate", "depth", "random_seed", "l2_leaf_reg", "thread_count"},
    "linear": {"estimator", "alpha", "fit_intercept"},
    "lstm": {
        "d_feat",
        "hidden_size",
        "num_layers",
        "dropout",
        "n_epochs",
        "lr",
        "early_stop",
        "batch_size",
        "metric",
        "loss",
        "GPU",
        "seed",
        "optimizer",
    },
    "gru": {
        "d_feat",
        "hidden_size",
        "num_layers",
        "dropout",
        "n_epochs",
        "lr",
        "early_stop",
        "batch_size",
        "metric",
        "loss",
        "GPU",
        "seed",
        "optimizer",
    },
    "alstm": {
        "d_feat",
        "hidden_size",
        "num_layers",
        "dropout",
        "n_epochs",
        "lr",
        "early_stop",
        "batch_size",
        "metric",
        "loss",
        "GPU",
        "seed",
        "optimizer",
    },
    "transformer": {
        "d_feat",
        "d_model",
        "nhead",
        "num_layers",
        "dropout",
        "n_epochs",
        "lr",
        "early_stop",
        "batch_size",
        "metric",
        "loss",
        "GPU",
        "seed",
        "optimizer",
        "reg",
    },
}
MODEL_KEYS |= set().union(*MODEL_ALLOWED.values())
SOURCE_FIELDS = (
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
)
STRATEGY_KEYS = {
    "risk_degree",
    "hold_thresh",
    "only_tradable",
    "forbid_all_trade_at_limit",
    "method_sell",
    "method_buy",
}
# D.features ultimately parses expressions. Limit that surface to arithmetic and
# these built-in numerical operators, never arbitrary names/attributes/callables.
EXPRESSION_OPERATORS = {
    "Ref",
    "Mean",
    "Sum",
    "Std",
    "Var",
    "Max",
    "Min",
    "Med",
    "Mad",
    "Rank",
    "Quantile",
    "Count",
    "EMA",
    "WMA",
    "Corr",
    "Cov",
    "Delta",
    "Abs",
    "Log",
    "Sign",
    "Power",
    "Greater",
    "Less",
    "If",
    "And",
    "Or",
    "Not",
    "Slope",
    "Rsquare",
    "Resi",
    "IdxMax",
    "IdxMin",
}
# Instrument switching is intentionally not exposed in expression input.
IDENTIFIER = re.compile(r"^[A-Za-z0-9_^.\-]{1,64}$")
JOB_ID = re.compile(r"^[0-9a-f]{32}$")


def validate_expression(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 300:
        raise ValueError("因子表达式必须为 1–300 字符")
    rewritten = re.sub(r"\$([A-Za-z][A-Za-z0-9_]*)", r"FIELD_\1", value)
    try:
        tree = ast.parse(rewritten, mode="eval")
    except SyntaxError as exc:
        raise ValueError("无效的因子表达式") from exc
    if not any(isinstance(node, ast.Name) and node.id.startswith("FIELD_") for node in ast.walk(tree)):
        raise ValueError("因子表达式必须包含 $field 数据字段")
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            if (
                not isinstance(node.right, ast.Constant)
                or not isinstance(node.right.value, (int, float))
                or abs(node.right.value) > 10
            ):
                raise ValueError("乘方只支持 -10 到 10 的常数指数")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in EXPRESSION_OPERATORS or node.keywords:
                raise ValueError("只允许内置数值因子运算符")
        elif isinstance(node, ast.Name):
            if node.id not in EXPRESSION_OPERATORS and not re.fullmatch(r"FIELD_[A-Za-z][A-Za-z0-9_]*", node.id):
                raise ValueError("因子表达式包含不支持的名称")
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                if not math.isfinite(node.value) or abs(node.value) > 10000:
                    raise ValueError("因子参数超出范围")
            else:
                raise ValueError("因子表达式只接受数值常量")
        elif not isinstance(
            node,
            (
                ast.Expression,
                ast.Load,
                ast.BinOp,
                ast.UnaryOp,
                ast.Add,
                ast.Sub,
                ast.Mult,
                ast.Div,
                ast.Pow,
                ast.Mod,
                ast.USub,
                ast.UAdd,
            ),
        ):
            raise ValueError("只允许数值表达式，不可执行 Python 代码")

    def scalar(node):
        # Bound intermediate constant arithmetic too; small exponents alone do
        # not prevent nested powers from allocating enormous Python integers.
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            left, right = scalar(node.left), scalar(node.right)
            if left is None or right is None:
                return None
            operators = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
                ast.Pow: operator.pow,
                ast.Mod: operator.mod,
            }
            try:
                result = operators[type(node.op)](left, right)
            except (OverflowError, ZeroDivisionError, TypeError, ValueError) as exc:
                raise ValueError("无效的数值表达式") from exc
            if not isinstance(result, (int, float)) or not math.isfinite(result) or abs(result) > 10000:
                raise ValueError("常量运算中间结果超出范围")
            return result
        if isinstance(node, ast.UnaryOp):
            value = scalar(node.operand)
            return None if value is None else (-value if isinstance(node.op, ast.USub) else value)
        for child in ast.iter_child_nodes(node):
            scalar(child)
        return None

    scalar(tree)
    return value


def check_kwargs(values: dict, allowed: set) -> dict:
    if len(values) > 50:
        raise ValueError("参数数量过多")
    unknown = set(values) - allowed
    if unknown:
        raise ValueError("不支持的高级参数: " + ", ".join(sorted(unknown)))

    def primitive(value, depth=0):
        if depth > 2:
            return False
        if value is None or isinstance(value, bool):
            return True
        if isinstance(value, (float, int)):
            return math.isfinite(value) and abs(value) <= 1e12
        if isinstance(value, str):
            return len(value) <= 300
        return isinstance(value, list) and len(value) <= 20 and all(primitive(v, depth + 1) for v in value)

    if not all(primitive(v) for v in values.values()):
        raise ValueError("高级参数只能包含有限数值、短字符串或简单列表")
    return values


class WorkflowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, protected_namespaces=())
    name: str = Field(default="我的研究", min_length=1, max_length=80)
    region: Literal["cn", "us"] = "cn"
    provider_uri: str = Field(default="~/.qlib/qlib_data/cn_data", min_length=1, max_length=1024)
    model: Literal["lightgbm", "xgboost", "catboost", "linear", "lstm", "gru", "transformer", "alstm"] = "lightgbm"
    handler: Literal["alpha158", "alpha360"] = "alpha158"
    strategy: Literal["topk_dropout", "topk_weighted", "conservative"] = "topk_dropout"
    time_range: Literal["default", "recent", "short", "long", "custom"] = "default"
    market: str = "csi300"
    benchmark: str = "SH000300"
    account: float = Field(default=100_000_000, gt=0, le=1e12)
    topk: int = Field(default=50, ge=1, le=10000)
    n_drop: int = Field(default=5, ge=0, le=10000)
    open_cost: float = Field(default=0.0005, ge=0, le=0.1)
    close_cost: float = Field(default=0.0015, ge=0, le=0.1)
    min_cost: float = Field(default=5, ge=0, le=1e6)
    train_start: date = date(2008, 1, 1)
    train_end: date = date(2014, 12, 31)
    valid_start: date = date(2015, 1, 1)
    valid_end: date = date(2016, 12, 31)
    test_start: date = date(2017, 1, 1)
    test_end: date = date(2020, 8, 1)
    model_kwargs: Dict[str, Any] = Field(default_factory=dict)
    handler_kwargs: Dict[str, Any] = Field(default_factory=dict)
    strategy_kwargs: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider_uri")
    @classmethod
    def local_provider(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("数据目录不能为空")
        if any(c in value for c in ("\x00", "\n", "\r")) or "://" in value or value.startswith("\\\\"):
            raise ValueError("数据源必须为本机 Qlib 数据目录，不支持 URL 或网络挂载")
        return value.strip()

    @field_validator("market", "benchmark")
    @classmethod
    def identifier(cls, value):
        if not IDENTIFIER.fullmatch(value):
            raise ValueError("市场/基准只接受代码，不接受路径或表达式")
        return value

    @field_validator("model_kwargs")
    @classmethod
    def model_options(cls, value):
        return check_kwargs(value, MODEL_KEYS)

    @field_validator("handler_kwargs")
    @classmethod
    def handler_options(cls, value):
        # filter_pipe can instantiate arbitrary classes. It intentionally is not
        # exposed, even though it is a valid Python handler parameter.
        check_kwargs(value, {"label", "drop_raw"})
        if "label" in value:
            labels = value["label"]
            if not isinstance(labels, list) or not labels or len(labels) > 5:
                raise ValueError("label 必须为 1–5 个表达式组成的数组")
            for label in labels:
                validate_expression(label)
        if "drop_raw" in value and not isinstance(value["drop_raw"], bool):
            raise ValueError("drop_raw 必须为布尔值")
        return value

    @field_validator("strategy_kwargs")
    @classmethod
    def strategy_options(cls, value):
        check_kwargs(value, STRATEGY_KEYS)
        if "risk_degree" in value and not (
            isinstance(value["risk_degree"], (int, float)) and 0 < value["risk_degree"] <= 1
        ):
            raise ValueError("risk_degree 必须在 (0, 1] 范围内")
        return value

    @model_validator(mode="after")
    def consistent(self):
        dates = [self.train_start, self.train_end, self.valid_start, self.valid_end, self.test_start, self.test_end]
        if any(start > end for start, end in zip(dates[::2], dates[1::2])):
            raise ValueError("每个数据集的开始日期不可晚于结束日期")
        if not (self.train_end < self.valid_start and self.valid_end < self.test_start):
            raise ValueError("训练、验证、测试区间必须严格按顺序且互不重叠，避免数据泄漏")
        if self.n_drop > self.topk:
            raise ValueError("淘汰数 n_drop 不可大于持仓数 topk")
        unsupported = set(self.model_kwargs) - MODEL_ALLOWED[self.model]
        if unsupported:
            raise ValueError(f"{self.model} 不支持这些构造参数: " + ", ".join(sorted(unsupported)))
        if self.model in {"lstm", "gru", "alstm", "transformer"}:
            expected = 6 if self.handler == "alpha360" else 158
            if "d_feat" in self.model_kwargs and self.model_kwargs["d_feat"] != expected:
                raise ValueError(f"{self.handler} 对应的 d_feat 必须是 {expected}")
        return self


class FeatureQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruments: List[str] = Field(min_length=1, max_length=20)
    fields: List[str] = Field(default_factory=lambda: ["$close", "$volume"], min_length=1, max_length=10)
    start_time: date
    end_time: date

    @field_validator("instruments")
    @classmethod
    def symbols(cls, values):
        if any(not IDENTIFIER.fullmatch(value) for value in values):
            raise ValueError("无效的证券代码")
        return values

    @field_validator("fields")
    @classmethod
    def expressions(cls, values):
        return [validate_expression(value) for value in values]

    @model_validator(mode="after")
    def dates(self):
        if not 0 <= (self.end_time - self.start_time).days <= 3660:
            raise ValueError("查询范围必须有效且不超过 10 年")
        return self


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["pipeline", "train", "backtest", "inspect", "features"]
    config: WorkflowConfig
    source_job_id: Optional[str] = None
    query: Optional[FeatureQuery] = None

    @model_validator(mode="after")
    def required(self):
        if self.source_job_id and not JOB_ID.fullmatch(self.source_job_id):
            raise ValueError("无效的源任务 ID")
        if self.kind == "backtest" and not self.source_job_id:
            raise ValueError("单独回测需要先选择已完成的训练实验")
        if self.kind == "features" and not self.query:
            raise ValueError("因子查询缺少查询条件")
        return self


def build_workflow(config: WorkflowConfig, include_backtest: bool = True) -> dict:
    """Compile only code-owned classes and validated primitive configuration."""
    if isinstance(config, dict):
        config = WorkflowConfig.model_validate(config)
    builder = ConfigBuilder().set_region(config.region).set_model(config.model).set_handler(config.handler)
    builder.set_strategy(config.strategy).set_account(config.account)
    task = builder.build_task_config()
    model = task["model"]
    if config.model == "transformer":
        model["class"] = "TransformerModel"  # preset formerly targeted the inner torch module
    if config.model in {"lstm", "gru", "alstm", "transformer"}:
        model["kwargs"].update(d_feat=6 if config.handler == "alpha360" else 158, GPU=-1)
    if config.model == "lightgbm":
        model["kwargs"]["num_threads"] = 4
    # The existing XGBoost/CatBoost wrappers set rounds in fit(), not their
    # constructors. Remove misleading CLI defaults rather than export no-op knobs.
    if config.model == "xgboost":
        model["kwargs"].pop("n_estimators", None)
    if config.model == "catboost":
        model["kwargs"].pop("iterations", None)
    if config.model == "alstm":
        model["kwargs"].pop("rnn_type", None)
    model["kwargs"].update(copy.deepcopy(config.model_kwargs))
    handler = task["dataset"]["kwargs"]["handler"]["kwargs"]
    handler.update(
        start_time=str(config.train_start),
        end_time=str(config.test_end),
        fit_start_time=str(config.train_start),
        fit_end_time=str(config.train_end),
        instruments=config.market,
    )
    if config.handler == "alpha158" and config.model in {"lstm", "gru", "alstm", "transformer"}:
        handler["infer_processors"] = [
            {"class": "ProcessInf", "kwargs": {}},
            {"class": "ZScoreNorm", "kwargs": {"fields_group": "feature"}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ]
    handler.update(copy.deepcopy(config.handler_kwargs))
    task["dataset"]["kwargs"]["segments"] = {
        "train": [str(config.train_start), str(config.train_end)],
        "valid": [str(config.valid_start), str(config.valid_end)],
        "test": [str(config.test_start), str(config.test_end)],
    }
    backtest = builder.build_backtest_config()
    backtest["strategy"]["kwargs"].update(topk=config.topk, n_drop=config.n_drop, signal="<PRED>")
    backtest["strategy"]["kwargs"].update(copy.deepcopy(config.strategy_kwargs))
    backtest["backtest"].update(
        start_time=str(config.test_start), end_time=str(config.test_end), benchmark=config.benchmark
    )
    backtest["backtest"]["exchange_kwargs"].update(
        open_cost=config.open_cost,
        close_cost=config.close_cost,
        min_cost=config.min_cost,
        trade_unit=REGIONS[config.region]["trade_unit"],
    )
    task["record"] = [
        {
            "class": "SignalRecord",
            "module_path": "qlib.workflow.record_temp",
            "kwargs": {"model": "<MODEL>", "dataset": "<DATASET>"},
        },
        {
            "class": "SigAnaRecord",
            "module_path": "qlib.workflow.record_temp",
            "kwargs": {"ana_long_short": False, "ann_scaler": 252},
        },
    ]
    if include_backtest:
        task["record"].append(
            {"class": "PortAnaRecord", "module_path": "qlib.workflow.record_temp", "kwargs": {"config": backtest}}
        )
    return {"qlib_init": {"provider_uri": config.provider_uri, "region": config.region}, "task": task}


def config_warnings(config: WorkflowConfig) -> list:
    warnings = ["回测仅用于研究，不代表未来收益，也不会连接券商或下单。"]
    if config.model in {"xgboost", "catboost"}:
        warnings.append("该 Qlib 原生包装器使用 fit() 默认的 1000 轮与 50 轮早停；网页不接收会被忽略的轮数构造参数。")
    if config.strategy == "topk_weighted":
        warnings.append("现有 topk_weighted 预设实际使用 TopkDropoutStrategy，是集中持仓参数，不是独立的加权策略。")
    if config.model in {"lstm", "gru", "alstm", "transformer"}:
        warnings.append("深度学习默认使用 CPU；可通过高级参数 GPU 选择已安装的 CUDA 设备。")
    if config.handler == "alpha158" and config.model in {"lstm", "gru", "alstm", "transformer"}:
        warnings.append("Alpha158 在这些模型中作为单步特征；如需 60 步时序窗口，请选择 Alpha360。")
    return warnings


def available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def catalog() -> dict:
    models = copy.deepcopy(MODEL_PRESETS)
    for key, value in models.items():
        value.update(dependency=DEPENDENCIES[key], available=available(DEPENDENCIES[key]))
    models["transformer"]["class"] = "TransformerModel"
    models["xgboost"]["kwargs"].pop("n_estimators", None)
    models["catboost"]["kwargs"].pop("iterations", None)
    models["alstm"]["kwargs"].pop("rnn_type", None)
    for key, value in models.items():
        value["allowed_kwargs"] = sorted(MODEL_ALLOWED[key])
    strategies = copy.deepcopy(STRATEGY_PRESETS)
    strategies["topk_weighted"].update(
        name="集中持仓 TopK", description="与 TopK-Dropout 相同算法，默认持仓 30、淘汰 10；非独立加权算法"
    )
    templates = [
        {"id": "classic", "name": "经典因子选股", "description": "LightGBM · Alpha158 · TopK-Dropout", "config": {}},
        {
            "id": "sequence",
            "name": "时序深度学习",
            "description": "LSTM · Alpha360 · CPU 默认",
            "config": {"model": "lstm", "handler": "alpha360"},
        },
        {
            "id": "conservative",
            "name": "低换手研究",
            "description": "XGBoost · 80 只持仓 · 每期淘汰 3 只",
            "config": {"model": "xgboost", "strategy": "conservative", "topk": 80, "n_drop": 3},
        },
        {
            "id": "attention",
            "name": "注意力时序",
            "description": "Transformer · Alpha360 · 集中持仓",
            "config": {
                "model": "transformer",
                "handler": "alpha360",
                "strategy": "topk_weighted",
                "topk": 30,
                "n_drop": 10,
            },
        },
        {
            "id": "baseline",
            "name": "快速基线",
            "description": "线性模型 · 短期验证",
            "config": {
                "model": "linear",
                "time_range": "short",
                **{
                    f"{seg}_{side}": TIME_PRESETS["short"][seg][i]
                    for seg in ("train", "valid", "test")
                    for i, side in enumerate(("start", "end"))
                },
            },
        },
    ]
    capabilities = [
        ("数据管理与因子查询", "ready", "本地数据检查、交易日历、证券池、受限数值表达式查询", "component/data.html"),
        (
            "训练、预测与信号分析",
            "ready",
            "8 个内置模型、Alpha158/360、IC/Rank IC 和预测导出",
            "component/workflow.html",
        ),
        ("策略回测与报告", "ready", "3 组 TopK 参数、费用/基准、净值/回撤与 CSV 报告", "component/strategy.html"),
        ("实验与任务管理", "ready", "控制台内实验比较、持久化日志、取消与失败原因", "component/recorder.html"),
        ("高级配置与导出", "ready", "经过验证的参数、配置保存与原生 qrun YAML 导出", "component/workflow.html"),
        (
            "数据采集 / 增量更新",
            "external",
            "需先运行仓库 scripts/data_collector；控制台不隐式下载或覆盖数据",
            "component/data.html",
        ),
        (
            "在线学习 / 滚动训练",
            "external",
            "请使用 examples/online_srv 与 examples/rolling 的 Python 工作流",
            "component/online.html",
        ),
        (
            "强化学习 / 高频执行 / 风险模型",
            "external",
            "目前提供功能导航；需要专用数据、环境与 Python 配置，未包装成可运行表单",
            "component/rl.html",
        ),
        (
            "自定义 Python 扩展",
            "external",
            "通过代码审查添加预设；网页不执行任意 Python 或上传的 pickle",
            "component/model.html",
        ),
    ]
    return {
        "models": models,
        "handlers": DATASET_HANDLERS,
        "strategies": strategies,
        "regions": REGIONS,
        "times": TIME_PRESETS,
        "templates": templates,
        "default_config": WorkflowConfig().model_dump(mode="json"),
        "capabilities": [
            {"name": n, "status": s, "description": d, "url": "https://qlib.readthedocs.io/en/latest/" + u}
            for n, s, d, u in capabilities
        ],
    }
