"""Worker contract tests. Qlib work is mocked here; no fake API success mode exists."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch
from uuid import uuid4

import numpy as np
import pandas as pd

from qlib_trader.web import runner
from qlib_trader.web.schema import WorkflowConfig, build_workflow


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.storage = Path(self.tmp.name)
        self.job = self.storage / "jobs" / uuid4().hex
        self.job.mkdir(parents=True)
        self.artifacts = self.job / "artifacts"
        self.artifacts.mkdir()
        self.config = WorkflowConfig(model="linear")
        self.dates = pd.date_range("2017-01-02", periods=3, freq="B")
        self.pred = pd.DataFrame(
            {"score": [0.01, -0.02, 0.03]},
            index=pd.MultiIndex.from_product([self.dates, ["SH600000"]], names=["datetime", "instrument"]),
        )
        self.label = self.pred.rename(columns={"score": "LABEL0"})
        self.report = pd.DataFrame(
            {"return": [0.1, -0.1, 0.02], "bench": [0.02, -0.01, 0.03], "cost": [0.01, 0.01, 0.0]}, index=self.dates
        )
        self.objects = {
            "pred.pkl": self.pred,
            "label.pkl": self.label,
            "sig_analysis/ic.pkl": pd.Series([0.1, np.nan, 0.2], index=self.dates),
            "sig_analysis/ric.pkl": pd.Series([0.1, 0.3, 0.2], index=self.dates),
            "portfolio_analysis/report_normal_1day.pkl": self.report,
            "portfolio_analysis/port_analysis_1day.pkl": pd.DataFrame({"risk": [0.12]}, index=["annualized_return"]),
        }
        self.recorder = MagicMock()
        self.recorder.id = "a" * 32
        self.recorder.get_artifact_uri.return_value = (
            self.storage / "mlruns" / "1" / self.recorder.id / "artifacts"
        ).as_uri()
        self.recorder.list_metrics.return_value = {"IC": 0.12, "ICIR": np.inf, "Rank IC": np.nan}
        self.recorder.load_object.side_effect = lambda path: self.objects[path]

    def write_request(self, kind="train", **extra):
        request = {"kind": kind, "config": self.config.model_dump(mode="json"), **extra}
        (self.job / "request.json").write_text(json.dumps(request))
        return request

    def make_source(self, status="completed"):
        source = self.storage / "jobs" / uuid4().hex
        source.mkdir()
        (source / "state.json").write_text(json.dumps({"status": status}))
        (source / "request.json").write_text(
            json.dumps({"kind": "train", "config": self.config.model_dump(mode="json")})
        )
        result = {"experiment_name": "console-" + source.name, "recorder_id": "b" * 32}
        (source / "result.json").write_text(json.dumps(result))
        return source, result

    def test_import_is_lightweight(self):
        result = subprocess.run(
            [sys.executable, "-c", "import sys; import qlib_trader.web.runner; assert 'qlib' not in sys.modules"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_series_is_net_arithmetic_cumulative_not_percent_or_compounded(self):
        series = runner._series(self.report)
        self.assertAlmostEqual(series[0]["return"], 0.09)
        self.assertAlmostEqual(series[1]["return"], -0.02)
        self.assertAlmostEqual(series[1]["benchmark"], 0.01)
        self.assertAlmostEqual(series[1]["excess"], -0.03)
        self.assertAlmostEqual(series[1]["drawdown"], -0.11)
        self.assertEqual(series[0]["date"], "2017-01-02")

    def test_initial_loss_counts_as_drawdown(self):
        self.report["return"] = [-0.05, 0.0, 0.02]
        self.assertAlmostEqual(runner._series(self.report)[0]["drawdown"], -0.06)

    def test_report_missing_benchmark_is_not_fabricated(self):
        self.report.loc[self.dates[0], "bench"] = np.nan
        with self.assertRaisesRegex(runner.JobError, "non-finite"):
            runner._series(self.report)
        with self.assertRaises(runner.JobError):
            runner._series(self.report.drop(columns="cost"))

    def test_preview_has_dates_codes_and_json_null(self):
        self.pred.iloc[0, 0] = np.nan
        preview = runner._preview(self.pred)
        self.assertEqual(preview["columns"], ["datetime", "instrument", "score"])
        self.assertIsNone(preview["rows"][0]["score"])
        self.assertTrue(preview["rows"][0]["datetime"].startswith("2017-01-02"))
        json.dumps(preview, allow_nan=False)

    def test_collect_uses_actual_daily_paths_and_safe_exports(self):
        result = runner._collect(self.recorder, "console-test", self.artifacts, self.storage, True)
        self.assertEqual(result["metrics"], {"IC": 0.12})
        self.assertEqual(result["summary"]["prediction_rows"], 3)
        self.assertEqual(set(result["summary"]["omitted_nonfinite_metrics"]), {"ICIR", "Rank IC"})
        self.assertEqual(len(result["series"]), 3)
        self.assertTrue((self.artifacts / "portfolio_report.csv").is_file())
        self.assertTrue((self.artifacts / "risk_analysis.csv").is_file())
        self.assertTrue((self.artifacts / "performance.csv").is_file())
        self.assertNotIn("portfolio_analysis", [x.args[0] for x in self.recorder.load_object.call_args_list])
        self.assertTrue(all(path.suffix in {".csv", ".json"} for path in self.artifacts.iterdir()))
        json.dumps(result, allow_nan=False)

    def test_collect_train_skips_portfolio_artifacts(self):
        result = runner._collect(self.recorder, "console-test", self.artifacts, self.storage, False)
        self.assertEqual(result["series"], [])
        self.assertFalse(any("portfolio_analysis/" in x.args[0] for x in self.recorder.load_object.call_args_list))

    def test_collect_empty_predictions_fails(self):
        self.objects["pred.pkl"] = pd.DataFrame()
        with self.assertRaisesRegex(runner.JobError, "no predictions"):
            runner._collect(self.recorder, "console-test", self.artifacts, self.storage, False)

    def test_collect_all_nan_predictions_fails(self):
        self.objects["pred.pkl"] = self.pred * np.nan
        with self.assertRaisesRegex(runner.JobError, "non-finite"):
            runner._collect(self.recorder, "console-test", self.artifacts, self.storage, False)

    def test_trusted_recorder_rejects_remote_or_outside_artifacts(self):
        for uri in ("https://example.com/pred.pkl", "file:///tmp/untrusted", "s3://bucket/run"):
            self.recorder.get_artifact_uri.return_value = uri
            with self.assertRaises(runner.JobError):
                runner._trusted_recorder(self.recorder, self.storage)

    def test_trusted_recorder_rejects_symlink_escape(self):
        (self.storage / "mlruns").mkdir()
        (self.storage / "mlruns" / "escape").symlink_to(self.job, target_is_directory=True)
        self.recorder.get_artifact_uri.return_value = (self.storage / "mlruns" / "escape").as_uri()
        with self.assertRaises(runner.JobError):
            runner._trusted_recorder(self.recorder, self.storage)

    def test_source_metadata_validates_completed_identity_and_data(self):
        source, expected = self.make_source()
        self.assertEqual(runner._source_metadata(source.name, self.config, self.job, self.storage), expected)
        mismatch = self.config.model_copy(update={"market": "csi500"})
        with self.assertRaisesRegex(runner.JobError, "market"):
            runner._source_metadata(source.name, mismatch, self.job, self.storage)
        (source / "state.json").write_text('{"status":"running"}')
        with self.assertRaisesRegex(runner.JobError, "completed"):
            runner._source_metadata(source.name, self.config, self.job, self.storage)

    def test_source_uuid_and_experiment_cannot_escape(self):
        for source in ("../secret", "x" * 32, self.job.name, None):
            with self.assertRaises(runner.JobError):
                runner._source_metadata(source, self.config, self.job, self.storage)
        source, result = self.make_source()
        result["experiment_name"] = "unrelated-private-experiment"
        (source / "result.json").write_text(json.dumps(result))
        with self.assertRaisesRegex(runner.JobError, "recorder reference"):
            runner._source_metadata(source.name, self.config, self.job, self.storage)

    def test_query_uses_schema_expression_whitelist(self):
        query = {
            "instruments": ["SH600000", "SH600000"],
            "fields": ["$close", "Ref($close, 1)"],
            "start_time": "2017-01-01",
            "end_time": "2017-01-31",
        }
        valid = runner._validate_query(query, self.config)
        self.assertEqual(valid["instruments"], ["SH600000"])
        self.assertEqual(valid["fields"][1], "Ref($close, 1)")
        for value in ("__import__('os').system('id')", "(lambda: 1)()", "$close.__class__", "open('/tmp/x')"):
            with self.assertRaises(ValueError):
                runner._validate_query({**query, "fields": [value]}, self.config)

    def test_feature_query_exports_actual_values(self):
        D = MagicMock()
        D.calendar.return_value = self.dates
        D.features.return_value = self.pred.rename(columns={"score": "$close"})
        query = {
            "instruments": ["SH600000"],
            "fields": ["$close"],
            "start_time": "2017-01-01",
            "end_time": "2017-01-31",
        }
        result = runner._features(D, self.config, query, self.artifacts)
        self.assertEqual(result["summary"]["row_count"], 3)
        self.assertAlmostEqual(result["preview"]["rows"][0]["$close"], 0.01)
        self.assertTrue((self.artifacts / "features.csv").is_file())
        self.assertEqual(D.features.call_args.kwargs["disk_cache"], 0)

    def test_empty_feature_data_fails(self):
        D = MagicMock()
        D.calendar.return_value = self.dates
        D.features.return_value = self.pred * np.nan
        query = {
            "instruments": ["SH600000"],
            "fields": ["$close"],
            "start_time": "2017-01-01",
            "end_time": "2017-01-31",
        }
        with self.assertRaisesRegex(runner.JobError, "no observations"):
            runner._features(D, self.config, query, self.artifacts)

    def test_inspect_uses_real_calendar_and_instrument_intervals(self):
        D = MagicMock()
        D.calendar.return_value = self.dates
        D.list_instruments.return_value = {"SH600000": [(self.dates[0], self.dates[-1])]}
        self.write_request("inspect")
        with patch.object(runner, "_initialize_qlib", return_value=(D, MagicMock())):
            result = runner.run_job(self.job, self.storage)
        self.assertEqual(result["summary"]["calendar_count"], 3)
        self.assertEqual(result["summary"]["instrument_count"], 1)
        self.assertTrue((self.job / "result.json").is_file())
        self.assertFalse((self.job / "state.json").exists())
        self.assertFalse((self.job / "result.json.tmp").exists())
        with self.assertRaisesRegex(runner.JobError, "already has a result"):
            runner.run_job(self.job, self.storage)

    def test_pipeline_passes_validated_task_to_real_entrypoint(self):
        self.write_request("pipeline")
        trainer = ModuleType("qlib.model.trainer")
        trainer._log_task_info = MagicMock()
        trainer._exe_task = MagicMock(side_effect=lambda task: self.assertIsNone(self.recorder.async_log))
        R = MagicMock()
        R.get_recorder.return_value = self.recorder
        with patch.dict(sys.modules, {"qlib.model.trainer": trainer}), patch.object(
            runner, "_initialize_qlib", return_value=(MagicMock(), R)
        ), patch.object(runner, "_preflight"):
            result = runner.run_job(self.job, self.storage)
        self.assertEqual(R.start.call_args.kwargs["experiment_name"], "console-" + self.job.name)
        self.assertEqual(trainer._exe_task.call_args.args[0]["record"][-1]["class"], "PortAnaRecord")
        self.assertEqual(trainer._log_task_info.call_args.args[0], trainer._exe_task.call_args.args[0])
        self.assertEqual(result["recorder_id"], self.recorder.id)

    def test_synchronous_recorder_drains_before_disabling_async_queue(self):
        pending = self.recorder.async_log
        pending.wait.side_effect = lambda: self.assertIs(self.recorder.async_log, pending)
        runner._synchronous_recorder(self.recorder)
        pending.wait.assert_called_once_with()
        self.assertIsNone(self.recorder.async_log)
        runner._synchronous_recorder(self.recorder)
        pending.wait.assert_called_once()

    def test_synchronous_recorder_does_not_suppress_flush_failure(self):
        self.recorder.async_log.wait.side_effect = RuntimeError("logging failure")
        with self.assertRaisesRegex(RuntimeError, "logging failure"):
            runner._synchronous_recorder(self.recorder)

    def test_backtest_copies_signal_into_a_new_recorder_only(self):
        source, source_result = self.make_source()
        old = MagicMock()
        old.get_artifact_uri.return_value = (self.storage / "mlruns" / "old" / "artifacts").as_uri()
        old.load_object.side_effect = lambda path: self.objects[path]
        R = MagicMock()
        R.get_recorder.side_effect = [old, self.recorder]
        records = ModuleType("qlib.workflow.record_temp")
        records.SigAnaRecord = MagicMock()
        records.PortAnaRecord = MagicMock()
        records.SigAnaRecord.return_value.generate.side_effect = lambda: self.assertIsNone(self.recorder.async_log)
        records.PortAnaRecord.return_value.generate.side_effect = lambda: self.assertIsNone(self.recorder.async_log)
        with patch.dict(sys.modules, {"qlib.workflow.record_temp": records}):
            result = runner._backtest(
                build_workflow(self.config), self.config, source_result, R, "console-" + self.job.name, self.storage
            )
        self.assertIs(result, self.recorder)
        self.assertEqual([x.args[0] for x in old.load_object.call_args_list], ["pred.pkl", "label.pkl"])
        old.save_objects.assert_not_called()
        self.assertEqual(set(self.recorder.save_objects.call_args.kwargs), {"pred.pkl", "label.pkl"})
        self.assertNotIn("resume", R.start.call_args.kwargs)
        self.assertNotIn("recorder_id", R.start.call_args.kwargs)
        records.SigAnaRecord.return_value.generate.assert_called_once()
        records.PortAnaRecord.return_value.generate.assert_called_once()

    @unittest.skipUnless(os.name == "posix", "POSIX process group assertion")
    def test_watchdog_terminates_orphan_worker_group(self):
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os,time; from qlib_trader.web.runner import _start_parent_watchdog; _start_parent_watchdog(os.getppid()+1000000); time.sleep(10)",
            ],
            capture_output=True,
            text=True,
            start_new_session=True,
            timeout=5,
        )
        self.assertIn(process.returncode, (-15, 1))
        self.assertIn("parent exited", process.stderr)

    def test_worker_lock_wraps_whole_job(self):
        locks = ModuleType("filelock")
        locks.Timeout = type("Timeout", (Exception,), {})
        locks.FileLock = MagicMock()
        expected = {"metrics": {}}
        with patch.dict(sys.modules, {"filelock": locks}), patch.object(
            runner, "run_job", return_value=expected
        ) as execute:
            self.assertEqual(runner._run_locked(self.job, self.storage), expected)
            execute.assert_called_once_with(self.job, self.storage)
            locks.FileLock.assert_called_once_with(str(self.storage / ".worker.lock"), timeout=15)
            locks.FileLock.return_value.acquire.assert_called_once()
            locks.FileLock.return_value.release.assert_called_once()

    def test_worker_lock_timeout_is_clear_and_does_not_start(self):
        locks = ModuleType("filelock")
        locks.Timeout = type("Timeout", (Exception,), {})
        locks.FileLock = MagicMock()
        locks.FileLock.return_value.acquire.side_effect = locks.Timeout()
        with patch.dict(sys.modules, {"filelock": locks}), patch.object(runner, "run_job") as execute:
            with self.assertRaisesRegex(runner.JobError, "Another Qlib worker"):
                runner._run_locked(self.job, self.storage)
            execute.assert_not_called()

    def test_failure_writes_no_success_or_state(self):
        self.write_request("train")
        errors = io.StringIO()
        with patch.object(
            runner, "_initialize_qlib", side_effect=ModuleNotFoundError("No module named 'mlflow'")
        ), contextlib.redirect_stderr(errors):
            code = runner.main(["--job-dir", str(self.job), "--storage-dir", str(self.storage)])
        self.assertEqual(code, 1)
        self.assertIn("Dependency error", errors.getvalue())
        self.assertIn("same Python environment", errors.getvalue())
        self.assertFalse((self.job / "result.json").exists())
        self.assertFalse((self.job / "state.json").exists())

    def test_invalid_source_stops_before_qlib_initialization(self):
        self.write_request("backtest", source_job_id="../outside")
        with patch.object(runner, "_initialize_qlib") as initialize:
            with self.assertRaises(runner.JobError):
                runner.run_job(self.job, self.storage)
            initialize.assert_not_called()

    def test_initialization_pins_tracking_and_prevents_inherited_run_resume(self):
        provider = self.storage / "data"
        (provider / "calendars").mkdir(parents=True)
        (provider / "calendars" / "day.txt").write_text("2017-01-02\n")
        (provider / "features").mkdir()
        config = self.config.model_copy(update={"provider_uri": str(provider)})
        qlib = ModuleType("qlib")
        qlib.init = MagicMock()
        data = ModuleType("qlib.data")
        data.D = MagicMock()
        workflow = ModuleType("qlib.workflow")
        workflow.R = MagicMock()
        with patch.dict(sys.modules, {"qlib": qlib, "qlib.data": data, "qlib.workflow": workflow}), patch.dict(
            os.environ, {"MLFLOW_RUN_ID": "existing-run", "MLFLOW_TRACKING_URI": "https://external.invalid"}
        ):
            runner._initialize_qlib(build_workflow(config), config, self.storage)
            self.assertNotIn("MLFLOW_RUN_ID", os.environ)
            self.assertEqual(os.environ["MLFLOW_TRACKING_URI"], (self.storage / "mlruns").as_uri())
            self.assertEqual(os.environ["MLFLOW_DISABLE_TELEMETRY"], "true")
            self.assertEqual(os.environ["MLFLOW_ENABLE_ASYNC_LOGGING"], "false")
            self.assertEqual(
                qlib.init.call_args.kwargs["exp_manager"]["kwargs"]["uri"], (self.storage / "mlruns").as_uri()
            )
            self.assertFalse(qlib.init.call_args.kwargs["auto_mount"])

    def test_missing_data_is_actionable_before_dependency_import(self):
        config = self.config.model_copy(update={"provider_uri": str(self.storage / "absent")})
        with self.assertRaisesRegex(runner.JobError, "Prepare Qlib binary market data"):
            runner._initialize_qlib(build_workflow(config), config, self.storage)

    def test_backtest_calendar_requires_extra_day(self):
        D = MagicMock()
        D.calendar.return_value = self.dates
        with self.assertRaisesRegex(runner.JobError, "one extra"):
            runner._preflight(D, self.config, "backtest")


@unittest.skipUnless(
    os.environ.get("QLIB_CONSOLE_INTEGRATION") == "1",
    "set QLIB_CONSOLE_INTEGRATION=1 with full Qlib dependencies and compiled extensions",
)
class RealQlibIntegration(unittest.TestCase):
    """Real binary data -> model.fit -> predictions -> backtest; no mocks.

    This seeded synthetic fixture is only a test input, never a console demo,
    fallback result, investment claim, or substitute for actual market data.
    """

    def test_all_job_kinds_on_real_qlib(self):
        with tempfile.TemporaryDirectory(prefix="qlib-console-real-") as directory:
            root = Path(directory)
            provider = root / "data"
            dates = pd.bdate_range("2020-01-02", periods=340)
            (provider / "calendars").mkdir(parents=True)
            (provider / "instruments").mkdir()
            (provider / "calendars" / "day.txt").write_text("\n".join(dates.strftime("%Y-%m-%d")) + "\n")
            symbols = [f"SH60000{x}" for x in range(8)]
            benchmark = "SH000300"
            spans = lambda values: "".join(
                f"{symbol}\t{dates[0]:%Y-%m-%d}\t{dates[-1]:%Y-%m-%d}\n" for symbol in values
            )
            (provider / "instruments" / "csi300.txt").write_text(spans(symbols))
            (provider / "instruments" / "all.txt").write_text(spans(symbols + [benchmark]))
            rng = np.random.default_rng(20261005)
            for index, symbol in enumerate(symbols + [benchmark]):
                close = (20 + index * 3) * np.exp(np.cumsum(rng.normal(0.0004, 0.012, len(dates))))
                opening = close * (1 + rng.uniform(-0.004, 0.004, len(dates)))
                high = np.maximum(close, opening) * (1 + rng.uniform(0.001, 0.012, len(dates)))
                low = np.minimum(close, opening) * (1 - rng.uniform(0.001, 0.012, len(dates)))
                volume = rng.uniform(2e6, 9e6, len(dates))
                features = {
                    "close": close,
                    "open": opening,
                    "high": high,
                    "low": low,
                    "vwap": (close + opening + high + low) / 4,
                    "volume": volume,
                    "factor": np.ones(len(dates)),
                }
                target = provider / "features" / symbol.lower()
                target.mkdir(parents=True)
                for name, values in features.items():
                    np.concatenate(([0], values)).astype("<f4").tofile(target / f"{name}.day.bin")
            config = WorkflowConfig(
                name="Synthetic integration test",
                model="linear",
                model_kwargs={"estimator": "ridge", "alpha": 1.0},
                provider_uri=str(provider),
                time_range="custom",
                topk=3,
                n_drop=1,
                account=1_000_000,
                train_start=dates[60].date(),
                train_end=dates[219].date(),
                valid_start=dates[220].date(),
                valid_end=dates[259].date(),
                test_start=dates[260].date(),
                test_end=dates[309].date(),
            )
            storage = root / "console"

            def execute(kind, **extra):
                job = storage / "jobs" / uuid4().hex
                job.mkdir(parents=True)
                request = {"kind": kind, "config": config.model_dump(mode="json"), **extra}
                (job / "request.json").write_text(json.dumps(request))
                process = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "qlib_trader.web.runner",
                        "--job-dir",
                        str(job),
                        "--storage-dir",
                        str(storage),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                (job / "logs.txt").write_text(process.stdout + "\n" + process.stderr)
                self.assertEqual(
                    process.returncode, 0, f"{kind} failed:\n{process.stdout[-2500:]}\n{process.stderr[-8500:]}"
                )
                result = json.loads((job / "result.json").read_text())
                (job / "state.json").write_text('{"status":"completed"}')
                return job, result

            inspected_job, inspected = execute("inspect")
            self.assertEqual(inspected["summary"]["calendar_count"], len(dates))
            self.assertEqual(inspected["summary"]["instrument_count"], 8)
            feature_job, features = execute(
                "features",
                query={
                    "instruments": symbols[:2],
                    "fields": ["$close", "Ref($close, 1)"],
                    "start_time": str(dates[260].date()),
                    "end_time": str(dates[264].date()),
                },
            )
            self.assertEqual(features["summary"]["row_count"], 10)
            self.assertTrue((feature_job / "artifacts" / "features.csv").is_file())
            training_job, trained = execute("train")
            self.assertEqual(trained["series"], [])
            self.assertEqual(trained["summary"]["prediction_rows"], 400)
            self.assertIn("IC", trained["metrics"])
            pipeline_job, pipeline = execute("pipeline")
            self.assertEqual(pipeline["summary"]["backtest_days"], 50)
            self.assertIn("1day.excess_return_with_cost.annualized_return", pipeline["metrics"])
            self.assertTrue((pipeline_job / "artifacts" / "risk_analysis.csv").is_file())
            source_result = (training_job / "result.json").read_bytes()
            backtest_job, backtested = execute("backtest", source_job_id=training_job.name)
            self.assertNotEqual(backtested["recorder_id"], trained["recorder_id"])
            self.assertNotEqual(backtested["experiment_name"], trained["experiment_name"])
            self.assertEqual(backtested["summary"]["source_job_id"], training_job.name)
            self.assertEqual(len(backtested["series"]), 50)
            self.assertEqual((training_job / "result.json").read_bytes(), source_result)
            # Running the same fitted signals and settings yields the same real report.
            self.assertEqual(backtested["series"], pipeline["series"])
            self.assertEqual(backtested["metrics"], pipeline["metrics"])
            # The web default also uses an actual small LightGBM training run.
            config = config.model_copy(
                update={
                    "model": "lightgbm",
                    "model_kwargs": {
                        "num_boost_round": 12,
                        "early_stopping_rounds": 5,
                        "num_leaves": 8,
                        "num_threads": 1,
                        "lambda_l1": 0.0,
                        "lambda_l2": 0.0,
                    },
                }
            )
            lgb_job, lgb_result = execute("pipeline")
            self.assertEqual(lgb_result["summary"]["prediction_rows"], 400)
            self.assertEqual(lgb_result["summary"]["backtest_days"], 50)
            self.assertIn("IC", lgb_result["metrics"])
            self.assertTrue((lgb_job / "artifacts" / "performance.csv").is_file())


if __name__ == "__main__":
    unittest.main()
