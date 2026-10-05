"""No Qlib runtime or market data required for configuration regression tests."""

import copy
import unittest

from pydantic import ValidationError

from qlib_trader.config import MODEL_PRESETS, STRATEGY_PRESETS
from qlib_trader.web.schema import (
    FeatureQuery,
    JobRequest,
    WorkflowConfig,
    build_workflow,
    catalog,
    validate_expression,
)


class SchemaTests(unittest.TestCase):
    def test_default_native_workflow(self):
        workflow = build_workflow(WorkflowConfig())
        self.assertEqual(workflow["task"]["model"]["class"], "LGBModel")
        self.assertEqual(len(workflow["task"]["record"]), 3)
        self.assertEqual(workflow["task"]["record"][2]["kwargs"]["config"]["strategy"]["kwargs"]["signal"], "<PRED>")

    def test_train_has_no_portfolio(self):
        workflow = build_workflow(WorkflowConfig(), include_backtest=False)
        self.assertEqual(len(workflow["task"]["record"]), 2)

    def test_all_catalog_models_compile_without_mutation(self):
        before = copy.deepcopy((MODEL_PRESETS, STRATEGY_PRESETS))
        for model in MODEL_PRESETS:
            for handler in ("alpha158", "alpha360"):
                workflow = build_workflow(WorkflowConfig(model=model, handler=handler, topk=8, n_drop=2))
                self.assertTrue(workflow["task"]["model"]["class"])
        self.assertEqual(before, (MODEL_PRESETS, STRATEGY_PRESETS))

    def test_transformer_targets_qlib_wrapper(self):
        model = build_workflow(WorkflowConfig(model="transformer", handler="alpha360"))["task"]["model"]
        self.assertEqual(model["class"], "TransformerModel")
        self.assertEqual(model["kwargs"]["d_feat"], 6)
        self.assertEqual(model["kwargs"]["GPU"], -1)

    def test_custom_dates_and_costs_reach_workflow(self):
        config = WorkflowConfig(
            test_end="2020-07-01",
            open_cost=0.002,
            market="csi500",
            topk=12,
            n_drop=1,
            model_kwargs={"learning_rate": 0.01},
            handler_kwargs={"label": ["Ref($close, -2) / Ref($close, -1) - 1"]},
        )
        workflow = build_workflow(config)
        port = workflow["task"]["record"][2]["kwargs"]["config"]
        self.assertEqual(port["backtest"]["end_time"], "2020-07-01")
        self.assertEqual(port["backtest"]["exchange_kwargs"]["open_cost"], 0.002)
        self.assertEqual(workflow["task"]["model"]["kwargs"]["learning_rate"], 0.01)
        self.assertEqual(workflow["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["instruments"], "csi500")

    def test_reject_leakage_nonfinite_unknown_kwargs_and_paths(self):
        invalid = [
            {"train_end": "2015-02-01"},
            {"valid_end": "2017-02-01"},
            {"test_end": "2010-01-01"},
            {"account": float("nan")},
            {"n_drop": 51},
            {"provider_uri": "https://evil.test/data"},
            {"market": "../../etc/passwd"},
            {"model_kwargs": {"module_path": "os"}},
            {"model_kwargs": {"loss": {"class": "exec"}}},
            {"handler_kwargs": {"filter_pipe": []}},
            {"strategy_kwargs": {"risk_degree": 2}},
            {"extra": "ignored?"},
        ]
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(ValidationError):
                WorkflowConfig(**config)

    def test_safe_numerical_expressions(self):
        for value in ("$close", "Mean($close, 5) / Ref($close, 1) - 1", "$close ** 2", "Corr($close, $volume, 20)"):
            self.assertEqual(validate_expression(value), value)
        for value in (
            "__import__('os').system('id')",
            "open('/etc/passwd')",
            "Ref.__globals__",
            "[x for x in []]",
            "9**9**9",
            "$close ** (9 ** 9)",
            "Ref($close, n=5)",
            "$close + 'a' * 1000000000",
            "Mean($close, 1000000000)",
            "$close + (((10000 ** 10) ** 10) ** 10)",
            "Mean($close, 10000 * 10000)",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_expression(value)

    def test_job_conditions_and_query_limits(self):
        with self.assertRaises(ValidationError):
            JobRequest(kind="backtest", config={})
        with self.assertRaises(ValidationError):
            JobRequest(kind="features", config={})
        with self.assertRaises(ValidationError):
            FeatureQuery(instruments=["../../"], start_time="2020-01-01", end_time="2020-02-01")
        with self.assertRaises(ValidationError):
            FeatureQuery(instruments=["SH600000"], start_time="2000-01-01", end_time="2020-02-01")

    def test_model_parameters_are_effective_and_neural_features_are_cleaned(self):
        for model, options in (
            ("xgboost", {"n_estimators": 2}),
            ("catboost", {"iterations": 2}),
            ("linear", {"learning_rate": 0.1}),
            ("lstm", {"d_feat": 6}),
        ):
            with self.subTest(model=model), self.assertRaises(ValidationError):
                WorkflowConfig(model=model, model_kwargs=options)
        task = build_workflow(WorkflowConfig(model="lstm"))["task"]
        processors = task["dataset"]["kwargs"]["handler"]["kwargs"]["infer_processors"]
        self.assertEqual([x["class"] for x in processors], ["ProcessInf", "ZScoreNorm", "Fillna"])
        self.assertNotIn("iterations", build_workflow(WorkflowConfig(model="catboost"))["task"]["model"]["kwargs"])

    def test_catalog_is_explicit_about_coverage(self):
        data = catalog()
        self.assertEqual(len(data["models"]), 8)
        self.assertEqual(len(data["templates"]), 5)
        self.assertTrue(any(item["status"] == "external" for item in data["capabilities"]))
        for template in data["templates"]:
            WorkflowConfig(**{**data["default_config"], **template["config"]})
